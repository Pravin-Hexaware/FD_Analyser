import json
import os
from typing import List, Dict, Any

import pandas as pd  # type: ignore

class HTMLDataRepository:
    def __init__(self, base_dir: str = "."):
        self.base_dir = base_dir

    def save_to_json(self, data: List[Dict[str, Any]], filename: str = "extracted_from_html.json") -> str:
        """Save the extracted data to a JSON file."""
        filepath = os.path.join(self.base_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return filepath

    def save_to_csv(self, data: List[Dict[str, Any]], filename: str = "extracted_from_html.csv") -> str:
        """Save the extracted data to a CSV file."""
        filepath = os.path.join(self.base_dir, filename)
        pd.DataFrame(data).to_csv(filepath, index=False)
        return filepath

    def load_from_json(self, filename: str = "extracted_from_html.json") -> List[Dict[str, Any]]:
        """Load data from a JSON file."""
        filepath = os.path.join(self.base_dir, filename)
        if not os.path.exists(filepath):
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)