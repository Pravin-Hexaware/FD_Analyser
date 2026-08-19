from __future__ import annotations
import io
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

import requests
from urllib3.exceptions import InsecureRequestWarning

# Hard-require lxml (prefix-aware parsing + robust HTML/iXBRL handling)
try:
    from lxml import etree as ET  # type: ignore
except Exception:
    print("ERROR: This script requires 'lxml'. Install with: pip install lxml", file=sys.stderr)
    sys.exit(1)

# Disable SSL warnings
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

# ----------------------
# Constants / Config
# ----------------------
XBRLI_NS = "http://www.xbrl.org/2003/instance"

OUTPUT_DIR = "sample_outputs"

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

def strip_pre_xml_content(data: bytes) -> bytes:
    """
    Strip HTML comments, text, and other non-XML content that appears
    before the actual XML/XHTML root element.
    
    This handles cases where XML files have content like:
    - "This XML file does not appear to have any style information..."
    - HTML comments
    - Other text nodes
    
    before the actual root element (e.g., <xbrli:xbrl> or <html>).
    """
    try:
        # Find the first '<' character which marks the start of XML/markup
        text = data.decode("utf-8", errors="ignore")
        first_bracket = text.find("<")
        
        if first_bracket > 0:
            # Strip everything before the first '<'
            cleaned = text[first_bracket:].encode("utf-8")
            return cleaned
        elif first_bracket == 0:
            # Already starts with '<', no stripping needed
            return data
        else:
            # No '<' found, return original data
            return data
    except Exception:
        # If any error occurs, return original data
        return data


def parse_xml_bytes(data: bytes) -> ET._ElementTree:
    """Parse bytes into an XML tree allowing recovery for messy iXBRL."""
    # Strip any pre-XML content (HTML comments, text nodes, etc.)
    cleaned_data = strip_pre_xml_content(data)
    parser = ET.XMLParser(recover=True, huge_tree=True)
    return ET.parse(io.BytesIO(cleaned_data), parser=parser)

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

def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


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
    txt = normalize_whitespace(value_text)
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
        adj = num / (10 ** (abs(d)))
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
    txt = normalize_whitespace(el.text or "")
    return txt != ""

def walk_collect(root: ET._Element, only_prefix: Optional[str]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Walk the tree in document order and collect elements grouped by localname.
    For each localname, capture all occurrences with their contextRef, unitRef, decimals, value.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    
    for el in root.iter():
        if not should_keep(el, only_prefix):
            continue

        raw_value = normalize_whitespace(el.text or "")
        decimals = el.get("decimals")
        adjusted_value = apply_decimals(raw_value, decimals)
        local = localname(el.tag)
        
        # Build record for this occurrence
        record = {
            "contextRef": el.get("contextRef"),
            "unitRef": el.get("unitRef"),
            #"decimals": decimals,
            "value": adjusted_value,
        }
        
        # Group by localname
        if local not in grouped:
            grouped[local] = []
        grouped[local].append(record)
    
    return grouped

# ----------------------
# Main Extractor
# ----------------------
def load_tree_from_bytes(data: bytes) -> ET._ElementTree:
    """Parse raw XML bytes into an element tree."""
    return parse_xml_bytes(data)

def extract_xbrl_data_from_bytes(content: bytes, only_prefix: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Extract XBRL data from raw XML bytes."""
    tree = load_tree_from_bytes(content)
    xbrl_root = get_xbrl_root(tree)
    extracted = walk_collect(xbrl_root, only_prefix)
    if only_prefix is not None and not extracted:
        # Fallback: if prefix filtering yields nothing, retry without prefix filtering.
        extracted = walk_collect(xbrl_root, None)
    return extracted


def extract_xbrl_data(url: str, only_prefix: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:

    """Extract XBRL data from a URL."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
        }
        response = requests.get(url, headers=headers, timeout=30, verify=False)
        response.raise_for_status()
        content = response.content
        return extract_xbrl_data_from_bytes(content, only_prefix)
    except Exception as e:
        print(f"Error fetching or parsing XBRL from {url}: {e}", file=sys.stderr)
        return {}


def get_xbrl_root(tree: ET._ElementTree) -> ET._Element:
    """
    Return the <xbrli:xbrl> root for both XML and HTML iXBRL.
    - If HTML, extract subtree
    - If XML and root is already <xbrli:xbrl>, return it
    - Else search for it anywhere inside as a fallback
    """
    root = tree.getroot()
    if root is None:
        raise ValueError("Failed to parse XML: no root element found.")
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




if __name__ == "__main__":
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        print("Enter path to XML / XBRL file: ", end="")
        file_path = input().strip()

    if not os.path.isfile(file_path):
        print("Invalid file path.")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(file_path, "rb") as f:
        content = f.read()

    parsed_json = extract_xbrl_data_from_bytes(content, only_prefix="in-bse-fin")

    out_path = os.path.join(
        OUTPUT_DIR,
        os.path.basename(file_path) + ".json"
    )

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(parsed_json, f, ensure_ascii=False, separators=(',', ':'))

    print(f"[OK] Structured JSON written to: {out_path}")