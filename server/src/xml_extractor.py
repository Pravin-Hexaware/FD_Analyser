from __future__ import annotations
import argparse
import io
import json
import sys
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd  # type: ignore
import requests      # type: ignore

# Hard-require lxml (prefix-aware parsing + robust HTML/iXBRL handling)
try:
    from lxml import etree as ET  # type: ignore
except Exception:
    print("ERROR: This script requires 'lxml'. Install with: pip install lxml", file=sys.stderr)
    sys.exit(1)

# NEW: consistent CA bundle + retries
try:
    import certifi  # type: ignore
    CERTIFI_PATH = certifi.where()
except Exception:
    CERTIFI_PATH = None

from requests.adapters import HTTPAdapter  # type: ignore
from urllib3.util.retry import Retry       # type: ignore
import urllib3                             # type: ignore

# ----------------------
# Constants / Config
# ----------------------
XBRLI_NS = "http://www.xbrl.org/2003/instance"

DEFAULT_JSON = "extracted_from_xml.json"
DEFAULT_CSV  = "extracted_from_xml.csv"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

# OPTIONAL: if your company gives you a PEM for the enterprise root CA,
# put its full path here to keep verification ON with your corporate proxy.
ENTERPRISE_CA_BUNDLE: Optional[str] = None  # e.g., r"C:\certs\corp_root_bundle.pem"

# Robust retry policy for flaky edges
RETRY = Retry(
    total=5,
    connect=5,
    read=5,
    backoff_factor=0.8,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "HEAD"]),
    raise_on_status=False,
    respect_retry_after_header=True,
)

def _build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    adapter = HTTPAdapter(max_retries=RETRY, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

# ----------------------
# Helpers
# ----------------------
def localname(tag: str) -> str:
    """Return the local (unqualified) name for a QName/Clark name."""
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{"):  # Clark name: {uri}local
        return tag.split("}", 1)[1]
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag

def is_html_root(root: ET._Element) -> bool:
    """True if the root looks like HTML/XHTML (iXBRL container)."""
    return localname(root.tag).lower() in {"html", "xhtml"}

def fetch_url_bytes(url: str, timeout: int = 60) -> bytes:
    """Fetch bytes from URL with browser-like headers + retries + robust TLS."""
    s = _build_session()

    # Preferred verification: enterprise bundle > certifi > system default
    verify_opt: Optional[str | bool] = True
    if ENTERPRISE_CA_BUNDLE:
        verify_opt = ENTERPRISE_CA_BUNDLE
    elif CERTIFI_PATH:
        verify_opt = CERTIFI_PATH  # keep behavior consistent across hosts

    try:
        r = s.get(url, timeout=timeout, verify=verify_opt)
        r.raise_for_status()
        return r.content
    except requests.exceptions.SSLError as ssl_err:
        # Final fallback to keep you unblocked; prints a clear warning.
        print(
            f"WARNING: TLS verify failed ({ssl_err}). Retrying once with verify=False. "
            "For a secure fix, set ENTERPRISE_CA_BUNDLE to your org's root CA PEM.",
            file=sys.stderr,
        )
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = s.get(url, timeout=timeout, verify=False)
        r.raise_for_status()
        return r.content

def parse_xml_bytes(data: bytes) -> ET._ElementTree:
    """Parse bytes into an XML tree allowing recovery for messy iXBRL."""
    parser = ET.XMLParser(recover=True, huge_tree=True)
    return ET.parse(io.BytesIO(data), parser=parser)

def extract_xbrl_subtree_from_html(root: ET._Element) -> ET._Element:
    """
    Find the <xbrli:xbrl> element inside an HTML/XHTML iXBRL document using namespace-aware XPath.
    Raises if not found.
    """
    nodes = root.xpath("//*[local-name()='xbrl' and namespace-uri()=$ns]", ns=XBRLI_NS)
    if not nodes:
        raise ValueError("iXBRL detected, but <xbrli:xbrl> subtree not found.")
    return nodes[0]

def qname_for(el: ET._Element) -> str:
    """Return a readable QName 'prefix:local' when a prefix exists; else the local name."""
    pre = getattr(el, "prefix", None)
    loc = localname(el.tag)
    return f"{pre}:{loc}" if pre else loc

def apply_decimals(value_text: str, decimals_text: Optional[str]) -> Any:
    """
    If 'decimals' is an integer string:
      - if decimals < 0: divide by 10^abs(decimals)
      - if decimals > 0: multiply by 10^decimals
    Else: return the original value_text as-is.

    If value_text is not a pure number, return as-is.
    """
    if value_text is None:
        return None

    # Try parse number
    txt = value_text.strip()
    if txt == "":
        return txt

    # Only adjust numeric content
    is_numeric = False
    # Accept integers and floats (no commas expected in XML instance numeric values)
    try:
        num = float(txt)
        is_numeric = True
    except Exception:
        is_numeric = False

    if not is_numeric:
        return value_text  # e.g., "Standalone", keep as-is

    # No decimals attribute → keep as-is
    if decimals_text is None:
        return value_text

    try:
        d = int(decimals_text)
    except Exception:
        return value_text

    if d < 0:
        # divide by 10^abs(d)
        adj = num / (10 ** abs(d))
        return adj
    elif d > 0:
        # multiply by 10^d
        adj = num * (10 ** d)
        return adj
    else:
        # d == 0 → unchanged
        return num  # keep numeric type

def should_keep(el: ET._Element, only_prefix: Optional[str]) -> bool:
    """
    Decide if this element should be kept:
    - If --only-prefix is set, require el.prefix == only_prefix
    - Keep only elements that carry non-empty textual values
    """
    if not isinstance(el.tag, str):
        return False
    if only_prefix is not None and getattr(el, "prefix", None) != only_prefix:
        return False
    txt = (el.text or "").strip()
    return txt != ""

def walk_collect(root: ET._Element, only_prefix: Optional[str]) -> List[Dict[str, Any]]:
    """
    Walk the tree in document order and collect elements that pass the filter.
    Captures qname, localname, contextRef, unitRef, decimals, value.
    Applies 'decimals' adjustment when present and numeric.
    """
    out: List[Dict[str, Any]] = []
    for el in root.iter():
        if not should_keep(el, only_prefix):
            continue

        raw_value = (el.text or "").strip()
        decimals = el.get("decimals")
        adjusted_value = apply_decimals(raw_value, decimals)

        out.append({
            "qname": qname_for(el),
            "localname": localname(el.tag),
            "contextRef": el.get("contextRef"),
            "unitRef": el.get("unitRef"),
            "decimals": decimals,
            "value": adjusted_value,
        })
    return out

# ----------------------
# Main Extractor
# ----------------------
def load_tree_from_url(url: str) -> ET._ElementTree:
    data = fetch_url_bytes(url)
    return parse_xml_bytes(data)

def get_xbrl_root(tree: ET._ElementTree) -> ET._Element:
    """
    Return the <xbrli:xbrl> root for both XML and HTML iXBRL.
    - If HTML, extract subtree
    - If XML and root is already <xbrli:xbrl>, return it
    - Else search for it anywhere inside as a fallback
    """
    root = tree.getroot()
    if is_html_root(root):
        return extract_xbrl_subtree_from_html(root)

    if localname(root.tag) == "xbrl":
        # Often already the instance root
        return root

    # Fallback: search anywhere
    hits = root.xpath("//*[local-name()='xbrl' and namespace-uri()=$ns]", ns=XBRLI_NS)
    if hits:
        return hits[0]

    # Some vendor docs might not use the standard ns (unlikely) — return root as last resort
    return root

def run(url: str, only_prefix: Optional[str], out_json: str, out_csv: str) -> Tuple[int, str, str]:
    tree = load_tree_from_url(url)
    xbrl_root = get_xbrl_root(tree)
    rows = walk_collect(xbrl_root, only_prefix)

    # Write outputs
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    pd.DataFrame(rows).to_csv(out_csv, index=False)

    return len(rows), out_json, out_csv

# ----------------------
# CLI
# ----------------------
def main():
    # Example XML instance from BSE:
    url = "https://www.bseindia.com/XBRLFILES/FourOneUploadDocument/Main_Ind_As_500470_2712025191552.xml"
    prefix = "in-bse-fin"  # filter to only keep that namespace prefix; set to None for all
    out_json = DEFAULT_JSON
    out_csv = DEFAULT_CSV

    try:
        n, jpath, cpath = run(url, prefix, out_json, out_csv)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"✅ Extracted {n} elements with non-empty values.")
    print(f"📄 JSON: {jpath}")
    print(f"📄 CSV : {cpath}")

if __name__ == "__main__":
    main()