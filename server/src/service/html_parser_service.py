from __future__ import annotations
import json
import os
import re
import sys
from typing import Any, Dict, Optional, List
from lxml import html as LXML_HTML
from lxml.etree import _Element, _ElementTree


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()

OUTPUT_DIR = "sample_outputs"
SKIP_PATTERNS = ["details of impact of audit qualification", "audit qualification", "impact of audit qualification"]


def read_file(file_path: str) -> bytes:
    with open(file_path, "rb") as f:
        return f.read()


def parse_html(content: bytes) -> _ElementTree:
    text = content.decode("utf-8", errors="replace")
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    root = LXML_HTML.fromstring(text.encode("utf-8"))
    return root.getroottree()


def extract_table(table: _Element) -> Any:
    rows = []
    tbody = table.find('.//tbody')
    if tbody is not None:
        for tr in tbody:
            if tr.tag.lower() == 'tr':
                cells = [normalize_whitespace(''.join(td.itertext())) for td in tr.findall('td')]
                if cells:
                    rows.append(cells)

    if not rows:
        return None

    # 2-column key-value table (only if all rows have exactly 2 columns)
    if len(rows) > 0 and len(rows[0]) == 2 and all(len(row) == 2 for row in rows):
        result = {}
        for row in rows:
            result[row[0]] = row[1]
        return result

    if len(rows) > 1:
        headers = rows[0]
        data_rows = rows[1:]
        normalized_rows = []
        previous_len = len(headers)

        for row in data_rows:
            last_cell_empty = bool(row) and row[-1].strip() == ''

            # ✅ BOTH CONDITIONS COMBINED
            if last_cell_empty:
                grouped_value = ' '.join(cell for cell in row if cell).strip()

                mapped = {headers[0]: grouped_value}
                for header in headers[1:]:
                    mapped[header] = ''

                normalized_rows.append(mapped)

            else:
                if len(row) <= len(headers):
                    mapped = {}
                    for j, header in enumerate(headers):
                        mapped[header] = row[j] if j < len(row) else ''
                    normalized_rows.append(mapped)
                else:
                    extra = len(row) - len(headers)
                    mapped = {headers[0]: ' '.join(row[:extra + 1]).strip()}
                    for j in range(1, len(headers)):
                        mapped[headers[j]] = row[extra + j]
                    normalized_rows.append(mapped)

            previous_len = len(row)

        return normalized_rows

    return rows


def build_structure(node: _Element) -> Any:
    if not isinstance(node, _Element):
        return None
    tag = node.tag.lower() if isinstance(node.tag, str) else str(node.tag).lower()
    if tag in ['html', 'head', 'body', 'div', 'ix:header']:
        result = {}
        last_heading_key = None
        encountered_skip = False
        i = 0
        while i < len(node):
            child = node[i]
            child_tag = child.tag.lower() if isinstance(child.tag, str) else str(child.tag).lower()
            if child_tag in ['h1', 'h2']:
                heading_text = normalize_whitespace(''.join(child.itertext()))
                skip_section = any(pattern in heading_text.lower() for pattern in SKIP_PATTERNS)
                i += 1
                content = []
                if skip_section:
                    encountered_skip = True
                    i = len(node)  # stop processing further children
                else:
                    while i < len(node):
                        next_child = node[i]
                        next_tag = next_child.tag.lower() if isinstance(next_child.tag, str) else str(next_child.tag).lower()
                        if next_tag in ['h1', 'h2']:
                            break
                        data = build_structure(next_child)
                        if data is not None:
                            content.append(data)
                        i += 1

                if not skip_section:
                    if heading_text.strip().lower() == 'text block' and last_heading_key is not None and content:
                        previous_value = result[last_heading_key]
                        if isinstance(previous_value, list):
                            previous_value.extend(content)
                        elif isinstance(previous_value, dict) and len(content) == 1 and isinstance(content[0], dict):
                            previous_value.update(content[0])
                        else:
                            result[last_heading_key] = [previous_value, *content] if previous_value is not None else content
                        continue

                    if len(content) == 1:
                        result[heading_text] = content[0]
                    elif len(content) > 1:
                        result[heading_text] = content
                    else:
                        result[heading_text] = {}
                    last_heading_key = heading_text
            else:
                if not encountered_skip:
                    data = build_structure(child)
                    if data is not None:
                        if isinstance(data, dict):
                            result.update(data)
                i += 1
        return result if result else None

    elif tag == 'table':
        table_data = extract_table(node)
        return table_data if table_data else None

    elif tag in ['br', 'meta', 'title', 'style'] or tag.startswith('ix:') or tag.startswith('xbrli:'):
        return None
    else:
        text = normalize_whitespace(''.join(node.itertext()))
        return text if text else None


def html_dom_to_structured_json_from_content(content: bytes) -> Dict[str, Any]:
    """Parse HTML content directly and return structured JSON."""
    tree = parse_html(content)
    root = tree.getroot()
    return build_structure(root) or {}


def html_dom_to_structured_json_from_file(file_path: str) -> Dict[str, Any]:
    content = read_file(file_path)
    tree = parse_html(content)
    root = tree.getroot()
    return build_structure(root) or {}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        print("Enter path to HTML / iXBRL file: ", end="")
        file_path = input().strip()

    if not os.path.isfile(file_path):
        print("Invalid file path.")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    dom_json = html_dom_to_structured_json_from_file(file_path)
    out_path = os.path.join(
        OUTPUT_DIR,
        os.path.basename(file_path) + ".json"
    )

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dom_json, f, ensure_ascii=False, separators=(',', ':'))

    print(f"[OK] Structured JSON written to: {out_path}")