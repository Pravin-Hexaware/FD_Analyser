from __future__ import annotations
import io
import json
import os
import re
import sys
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from requests.exceptions import SSLError
from urllib3.exceptions import InsecureRequestWarning

import pandas as pd  # type: ignore

# lxml
from lxml import etree as ET  # type: ignore
from lxml import html as LXML_HTML  # type: ignore

# Suppress TLS warnings since we fetch with verify=False (as requested)
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

# Try html5lib (preferred XHTML normalization)
try:
    import html5lib  # type: ignore
    HAS_HTML5LIB = True
except Exception:
    HAS_HTML5LIB = False

# -----------------------------
# HARD-CODED URL (EDIT THIS)
# -----------------------------
URL = "https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_544362_522026144018_IFIndAs.html"
# -----------------------------
# CONSTANTS / SETTINGS
# -----------------------------
OUTPUT_JSON = "extracted_from_html.json"
OUTPUT_CSV  = "extracted1_from_html.csv"

IX_NS = "http://www.xbrl.org/2013/inlineXBRL"
ALLOWED_INLINE_PREFIXES = {"ix", "ix2", "ix3"}  # in case alternate inline prefixes are used

# case-insensitive local-name() XPaths (primary: namespace-aware)
XPATH_IX_FACTS_NS = (
    "//*[namespace-uri()=$ixns and "
    "(translate(local-name(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='nonfraction' "
    " or translate(local-name(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='nonnumeric')]"
)
# fallback: accept elements by local-name only (if ns prefix was lost), still require @name
XPATH_IX_FACTS_ANY = (
    "//*[translate(local-name(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='nonfraction' "
    " or translate(local-name(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='nonnumeric']"
)

CAND_EXTS = (".xml", ".xbrl", ".xhtml", ".html", ".htm", ".zip")
REQUEST_TIMEOUT = 45
MAX_CANDIDATES = 30
VERBOSE = True


def log(msg: str) -> None:
    if VERBOSE:
        print(msg, file=sys.stderr)


# -----------------------------
# FETCH + PARSE (HTML → XHTML)
# -----------------------------
def fetch_html(url: str, referer: Optional[str] = None) -> bytes:
    """
    Fetch HTML bytes from URL.
    TLS verification is disabled (as per your earlier approach).
    """
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
    if referer:
        headers["Referer"] = referer
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, verify=False)
    resp.raise_for_status()
    return resp.content


def clean_html(content: bytes) -> bytes:
    """
    Clean control chars & normalize line endings.
    """
    text = content.decode("utf-8", errors="replace")
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.encode("utf-8")


def parse_html_to_tree(content: bytes) -> ET._ElementTree:
    """
    Prefer html5lib (XHTML with namespaces); fallback to lxml.html.
    """
    cleaned = clean_html(content)
    if HAS_HTML5LIB:
        try:
            doc = html5lib.parse(
                cleaned,
                treebuilder="lxml",
                namespaceHTMLElements=True
            )
            if not isinstance(doc, ET._ElementTree):
                doc = ET.ElementTree(doc)
            return doc
        except Exception:
            pass
    # Fallback: lxml.html -> ElementTree
    root = LXML_HTML.fromstring(cleaned)
    return ET.ElementTree(root)


def normalize_url(u: str) -> str:
    p = urlparse(u)
    p = p._replace(fragment="")
    return urlunparse(p)


def same_host(u: str, base: str) -> bool:
    return urlparse(u).netloc.lower() == urlparse(base).netloc.lower()


# -----------------------------
# iXBRL NAMESPACE ASSIST
# -----------------------------
def looks_like_ixbrl(doc: ET._ElementTree) -> bool:
    nf = doc.xpath("//*[translate(local-name(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='nonfraction']")
    nn = doc.xpath("//*[translate(local-name(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='nonnumeric']")
    return (len(nf) + len(nn)) > 0


def ensure_ixbrl_namespaces(root: ET._Element) -> None:
    """
    Ensure common iXBRL/XBRL namespaces on the root if inline facts exist.
    """
    ns_candidates = {
        "ix": IX_NS,
        "xbrli": "http://www.xbrl.org/2003/instance",
        "link": "http://www.xbrl.org/2003/linkbase",
        "xlink": "http://www.w3.org/1999/xlink",
        "xhtml": "http://www.w3.org/1999/xhtml",
    }
    declared = {}
    if hasattr(root, "nsmap") and root.nsmap:
        for pfx, uri in root.nsmap.items():
            if uri:
                declared[uri] = pfx

    doc = ET.ElementTree(root)
    if looks_like_ixbrl(doc):
        merged = dict(root.nsmap) if root.nsmap else {}
        changed = False
        for pfx, uri in ns_candidates.items():
            if uri not in declared:
                target = pfx
                i = 2
                while target in merged and merged[target] != uri:
                    target = f"{pfx}{i}"
                    i += 1
                merged[target] = uri
                changed = True
        if changed:
            new_root = ET.Element(root.tag, nsmap=merged)
            for k, v in root.attrib.items():
                new_root.set(k, v)
            new_root.text = root.text
            new_root.tail = root.tail
            for child in list(root):
                root.remove(child)
                new_root.append(child)
            parent = root.getparent()
            if parent is None:
                doc._setroot(new_root)
            else:
                parent.replace(root, new_root)


# -----------------------------
# EXTRACT iXBRL FACTS
# -----------------------------
def text_content(el: ET._Element) -> str:
    return "".join(el.itertext()).strip()


def get_attr(el: ET._Element, *names: str) -> Optional[str]:
    """
    Get first present attribute among given names (case-insensitive tolerant).
    """
    for n in names:
        v = el.get(n)
        if v is not None:
            return v
    for n in names:
        v = el.get(n.lower())
        if v is not None:
            return v
    for n in names:
        cap = n[:1].lower() + n[1:]
        v = el.get(cap)
        if v is not None:
            return v
    return None


def parse_indian_number(s: str) -> Optional[float]:
    """
    Convert '1,10,178.00' -> 110178.0; '(1,234.00)' -> -1234.0; '0.00' -> 0.0
    """
    if s is None:
        return None
    t = s.strip()
    if t == "":
        return None
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg = True
        t = t[1:-1]
    t = t.replace(",", "")
    try:
        v = float(t)
        return -v if neg else v
    except Exception:
        return None


def split_qname(qn: str) -> Tuple[Optional[str], str]:
    if ":" in qn:
        pre, loc = qn.split(":", 1)
        return pre, loc
    return None, qn


def extract_ix_facts_from_root(root: ET._Element) -> List[Dict[str, Any]]:
    """
    Extract iXBRL facts (ix:nonnumeric / ix:nonfraction) from the given root element.
    - Primary: strict ix namespace match (XPATH_IX_FACTS_NS)
    - Fallback: local-name only (XPATH_IX_FACTS_ANY) w/ prefix or @name sanity checks
    """
    ensure_ixbrl_namespaces(root)

    rows: List[Dict[str, Any]] = []
    # 1) strict ns
    ix_nodes = root.xpath(XPATH_IX_FACTS_NS, ixns=IX_NS)
    # 2) fallback union if none
    if not ix_nodes:
        ix_nodes = root.xpath(XPATH_IX_FACTS_ANY)

    for ix in ix_nodes:
        # sanity: if prefix exists, ensure it's one of inline prefixes
        pre = getattr(ix, "prefix", None)
        if pre is not None and pre.lower() not in ALLOWED_INLINE_PREFIXES:
            continue
        # must have @name (QName of concept)
        qn = get_attr(ix, "name")
        if not qn:
            continue

        contextref = get_attr(ix, "contextRef", "contextref")
        unitref    = get_attr(ix, "unitRef", "unitref")
        scale      = get_attr(ix, "scale")
        decimals   = get_attr(ix, "decimals")
        _, loc     = split_qname(qn)
        value_text = text_content(ix)

        is_nonfraction = isinstance(ix.tag, str) and ix.tag.lower().endswith("nonfraction")
        if is_nonfraction:
            value_num = parse_indian_number(value_text)
            rows.append({
                "qname": qn,
                "localname": loc,
                "contextref": contextref,
                "unitref": unitref,
                "scale": scale,
                "decimals": decimals,
                "value": value_num,
            })
        else:
            rows.append({
                "qname": qn,
                "localname": loc,
                "contextref": contextref,
                "unitref": unitref,
                "scale": scale,
                "decimals": decimals,
                "value": value_text,
            })
    return rows


# -----------------------------
# CANDIDATE DISCOVERY
# -----------------------------
def discover_candidates(root: ET._Element, base_url: str, raw_html: bytes) -> List[str]:
    """
    Collect same-host candidate URLs from DOM (iframe/a/link) and raw HTML via regex:
    Only keep URLs ending with .xml/.xbrl/.xhtml/.html/.htm/.zip
    """
    cands: List[str] = []

    # DOM-based
    for xp in ("//iframe[@src]", "//a[@href]", "//link[@href]"):
        for el in root.xpath(xp):
            attr = el.get("src") if "src" in el.attrib else el.get("href")
            if not attr:
                continue
            abs_u = normalize_url(urljoin(base_url, attr))
            if urlparse(abs_u).netloc.lower() != urlparse(base_url).netloc.lower():
                continue
            path = urlparse(abs_u).path.lower()
            if path.endswith(CAND_EXTS):
                cands.append(abs_u)

    # Regex-based
    try:
        text = raw_html.decode("utf-8", errors="ignore")
    except Exception:
        text = ""
    for m in re.findall(r'https?://[^\s"\'<>#]+', text, flags=re.IGNORECASE):
        abs_u = normalize_url(m)
        if urlparse(abs_u).netloc.lower() != urlparse(base_url).netloc.lower():
            continue
        path = urlparse(abs_u).path.lower()
        if path.endswith(CAND_EXTS):
            cands.append(abs_u)

    # de-dupe, prioritize by extension: xml > xhtml > html > zip
    uniq = list(dict.fromkeys(cands))
    def score(u: str) -> int:
        p = urlparse(u).path.lower()
        if p.endswith((".xml", ".xbrl")): return 4
        if p.endswith(".xhtml"):          return 3
        if p.endswith((".html", ".htm")): return 2
        if p.endswith(".zip"):            return 1
        return 0
    uniq.sort(key=score, reverse=True)
    return uniq[:MAX_CANDIDATES]


def try_parse_zip_and_extract(data: bytes) -> List[Dict[str, Any]]:
    """
    If bytes are a ZIP, scan .xml/.xbrl/.xhtml/.html entries and extract facts.
    """
    rows: List[Dict[str, Any]] = []
    if not data.startswith(b"PK\x03\x04"):
        return rows
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(CAND_EXTS)]
        # prefer xml/xbrl, then xhtml, then html
        names.sort(key=lambda n: (0 if n.lower().endswith((".xml", ".xbrl")) else (1 if n.lower().endswith(".xhtml") else 2), len(n)))
        for name in names:
            with zf.open(name) as f:
                b = f.read()
            try:
                # try as XML/XHTML
                tree = ET.parse(io.BytesIO(b), parser=ET.XMLParser(recover=True, huge_tree=True))
                rows = extract_ix_facts_from_root(tree.getroot())
                if rows:
                    return rows
            except Exception:
                # fallback to HTML parse
                try:
                    t = parse_html_to_tree(b)
                    rows = extract_ix_facts_from_root(t.getroot())
                    if rows:
                        return rows
                except Exception:
                    continue
    return rows


# -----------------------------
# MAIN
# -----------------------------
def main():
    try:
        #print(f"🔗 Fetching: {URL}")
        page = fetch_html(URL)
        tree = parse_html_to_tree(page)
        root = tree.getroot()

        # 1) Extract from main page
        rows = extract_ix_facts_from_root(root)
        if rows:
            # save and finish
            with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
            pd.DataFrame(rows).to_csv(OUTPUT_CSV, index=False)
            print(f"✅ Extracted {len(rows)} ix facts.")
            print(f"📄 JSON: {OUTPUT_JSON}")
            print(f"📄 CSV : {OUTPUT_CSV}")
            sys.exit(0)

        # 2) Discover same-host candidates and try them
        #print("ℹ️ No ix facts on main page; scanning same-host candidates...")
        cands = discover_candidates(root, URL, page)
        if not cands:
            print("ℹ️ No candidates discovered. The page may be a pure viewer.")
        else:
            for c in cands:
                try:
                    #log(f"➡️  Trying candidate: {c}")
                    data = fetch_html(c, referer=URL)

                    # zip path first
                    rows = try_parse_zip_and_extract(data)
                    if rows:
                        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
                            json.dump(rows, f, ensure_ascii=False, indent=2)
                        pd.DataFrame(rows).to_csv(OUTPUT_CSV, index=False)
                        print(f"✅ Extracted {len(rows)} ix facts (from ZIP candidate).")
                        print(f"📄 JSON: {OUTPUT_JSON}")
                        print(f"📄 CSV : {OUTPUT_CSV}")
                        sys.exit(0)

                    # try xml/xhtml/html parse
                    # attempt XML first
                    try:
                        t_xml = ET.parse(io.BytesIO(data), parser=ET.XMLParser(recover=True, huge_tree=True))
                        rows = extract_ix_facts_from_root(t_xml.getroot())
                        if rows:
                            with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
                                json.dump(rows, f, ensure_ascii=False, indent=2)
                            pd.DataFrame(rows).to_csv(OUTPUT_CSV, index=False)
                            print(f"✅ Extracted {len(rows)} ix facts (from XML/XHTML candidate).")
                            print(f"📄 JSON: {OUTPUT_JSON}")
                            print(f"📄 CSV : {OUTPUT_CSV}")
                            sys.exit(0)
                    except Exception:
                        pass

                    # fall back to HTML parser
                    t_html = parse_html_to_tree(data)
                    rows = extract_ix_facts_from_root(t_html.getroot())
                    if rows:
                        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
                            json.dump(rows, f, ensure_ascii=False, indent=2)
                        pd.DataFrame(rows).to_csv(OUTPUT_CSV, index=False)
                        print(f"✅ Extracted {len(rows)} ix facts (from HTML candidate).")
                        print(f"📄 JSON: {OUTPUT_JSON}")
                        print(f"📄 CSV : {OUTPUT_CSV}")
                        sys.exit(0)

                except Exception as e:
                    log(f"⚠️ Candidate failed: {c} -> {e}")
                    continue

        # 3) Nothing found
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        pd.DataFrame([], columns=["qname","localname","contextref","unitref","scale","decimals","value"]).to_csv(OUTPUT_CSV, index=False)
        print("✅ Extracted 0 ix facts.")
        print(f"📄 JSON: {OUTPUT_JSON}")
        print(f"📄 CSV : {OUTPUT_CSV}")
        print("ℹ️ Still no <ix:...> facts found. The page may be a pure viewer report; try a direct XML/iXBRL link.")

    except SSLError as e:
        print("❌ TLS/SSL error. If you're on a corporate network with SSL inspection, this is expected. (Fetching uses verify=False here.)", str(e))
        sys.exit(1)
    except Exception as e:
        print("❌ Failed:", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()