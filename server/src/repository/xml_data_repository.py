import json
import os
from typing import List, Dict, Any

import pandas as pd  # type: ignore

class XMLDataRepository:
    def __init__(self, base_dir: str = "."):
        self.base_dir = base_dir

    def save_to_json(self, data: Dict[str, List[Dict[str, Any]]], filename: str = "extracted_from_xml.json") -> str:
        """Save the extracted data to a JSON file."""
        filepath = os.path.join(self.base_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        return filepath

    def save_to_csv(self, data: Dict[str, List[Dict[str, Any]]], filename: str = "extracted_from_xml.csv") -> str:
        """Save the extracted data to a CSV file."""
        filepath = os.path.join(self.base_dir, filename)
        # Flatten the grouped data for CSV
        flattened = []
        for localname, records in data.items():
            for record in records:
                row = {"localname": localname}
                row.update(record)
                flattened.append(row)
        pd.DataFrame(flattened).to_csv(filepath, index=False)
        return filepath

    def load_from_json(self, filename: str = "extracted_from_xml.json") -> Dict[str, List[Dict[str, Any]]]:
        """Load data from a JSON file."""
        filepath = os.path.join(self.base_dir, filename)
        if not os.path.exists(filepath):
            return {}
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)