import json
from pathlib import Path
from typing import Dict, Optional
from loguru import logger
from paladino.config import settings

class GeoMapper:
    """Map Italian location strings to official ISTAT codes."""
    
    def __init__(self):
        self.mapping: Dict[str, str] = {}
        self._load_reference_data()
    
    def _load_reference_data(self):
        """Load ISTAT reference data (simplified for prototype)."""
        # In a real system, this would load a complete ISTAT CSV or JSON
        # For the prototype, we use a small internal map or a local JSON file
        ref_file = settings.data_dir / "istat_reference.json"
        
        if ref_file.exists():
            with open(ref_file, 'r', encoding='utf-8') as f:
                self.mapping = json.load(f)
        else:
            # Fallback for prototype
            self.mapping = {
                "MILANO": "015146",
                "ROMA": "058091",
                "TORINO": "001272",
                "NAPOLI": "063049",
                "PALERMO": "082053",
                "GENOVA": "010025",
                "BOLOGNA": "037006",
                "FIRENZE": "048017",
                "BARI": "072006",
                "CATANIA": "087015",
            }
            logger.warning(f"ISTAT reference file not found at {ref_file}. Using minimal fallback.")

    def get_istat_code(self, city_name: str) -> Optional[str]:
        """Get ISTAT code for a city name."""
        if not city_name:
            return None
        
        normalized = city_name.upper().strip()
        return self.mapping.get(normalized)

    def normalize_provincia(self, prov: str) -> str:
        """Normalize province code (e.g., 'Milano' -> 'MI')."""
        if not prov:
            return ""
        
        # Simplified for prototype - in production, use a full map
        prov_map = {
            "MILANO": "MI",
            "ROMA": "RM",
            "TORINO": "TO",
            "NAPOLI": "NA",
        }
        upper_prov = prov.upper().strip()
        return prov_map.get(upper_prov, upper_prov[:2])
