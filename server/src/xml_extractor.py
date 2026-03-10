from __future__ import annotations
import argparse
import sys
from typing import Any, Dict, List, Optional, Tuple

from service.xml_extraction_service import extract_xbrl_data
from repository.xml_data_repository import XMLDataRepository

# ----------------------
# Constants / Config
# ----------------------
DEFAULT_JSON = "extracted_from_xml.json"
DEFAULT_CSV  = "extracted_from_xml.csv"

# ----------------------
# Main Extractor
# ----------------------
def run(url: str, only_prefix: Optional[str], out_json: str, out_csv: str) -> Tuple[int, str, str]:
    rows = extract_xbrl_data(url, only_prefix)

    # Write outputs
    repo = XMLDataRepository()
    json_path = repo.save_to_json(rows, out_json)
    csv_path = repo.save_to_csv(rows, out_csv)

    return len(rows), json_path, csv_path

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