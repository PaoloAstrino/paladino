"""
ANAC OCDS transformation - Convert OCDS JSON to normalized graph schema.
"""

import json
import re
from datetime import datetime
from pathlib import Path

import polars as pl
from loguru import logger

from paladino.config import settings
from paladino.etl.normalizer import CompanyNormalizer


class AnacOcdsTransformer:
    """Transform ANAC OCDS JSON to normalized DataFrames."""

    def __init__(self, dataset_version: str | None = None):
        """
        Initialize transformer.

        Args:
            dataset_version: Version identifier for this dataset
        """
        self.source = "ANAC"
        self.dataset_version = dataset_version or settings.dataset_version
        self.retrieval_date = datetime.now().isoformat()

    def transform_file(self, ocds_file: Path) -> dict[str, pl.DataFrame]:
        """
        Transform a single OCDS file.

        Args:
            ocds_file: Path to OCDS JSON file

        Returns:
            Dictionary of DataFrames: tenders, companies, buyers, wins
        """
        logger.info(f"Transforming {ocds_file.name}")

        with open(ocds_file, encoding="utf-8") as f:
            ocds_data = json.load(f)

        return {
            "tenders": self.extract_tenders(ocds_data),
            "companies": self.extract_companies(ocds_data),
            "buyers": self.extract_buyers(ocds_data),
            "wins": self.extract_wins(ocds_data),
        }

    def _extract_releases(self, ocds_data: dict) -> list[dict]:
        """
        Extract release items from OCDS package (supports both formats).

        Args:
            ocds_data: OCDS JSON data (can be Release Package or Record Package)

        Returns:
            List of release dictionaries
        """
        if "records" in ocds_data:
            # Record Package format: extract first release from each record
            return [
                record.get("releases", [])[0]
                for record in ocds_data.get("records", [])
                if record.get("releases")
            ]
        # Release Package format
        return ocds_data.get("releases", [])

    def extract_tenders(self, ocds_data: dict) -> pl.DataFrame:
        """Extract tender nodes from OCDS data."""
        tenders = []

        items = self._extract_releases(ocds_data)
        cup_pattern = re.compile(r"([A-Z][0-9]{2}[A-Z][0-9]{11})")

        for release in items:
            # Extract identifiers
            id_val = release.get("ocid") or release.get("id", "")
            # Remove OCDS prefix if present (e.g., ocds-hu01ve-CIG)
            cig = id_val.split("-")[-1].split("/")[0] if id_val else ""

            tender_data = release.get("tender", {})

            # Extract tender information
            tender = {
                "id": self._generate_uuid(),
                "cig": cig,
                "ocid": id_val,
                "oggetto": tender_data.get("title", ""),
                "descrizione_estesa": tender_data.get("description", ""),
                "importo": self._extract_amount(tender_data.get("value", {})),
                "procedura": tender_data.get("procurementMethod", ""),
                "data_apertura": self._extract_date(
                    tender_data.get("tenderPeriod", {}).get("startDate")
                ),
                "data_aggiudicazione": self._extract_date(
                    tender_data.get("awardPeriod", {}).get("endDate")
                ),
                "source": self.source,
                "dataset_version": self.dataset_version,
                "retrieval_date": self.retrieval_date,
                "confidence": 0.95,
            }

            # Extract CUP from title or description
            text_to_scan = (tender["oggetto"] or "") + " " + (tender["descrizione_estesa"] or "")
            cup_match = cup_pattern.search(text_to_scan)
            tender["cup"] = cup_match.group(1) if cup_match else None

            # Only include tenders with valid CIG and amount (or if settings allow)
            if tender["cig"] and tender["importo"]:
                tenders.append(tender)

        df = pl.DataFrame(tenders) if tenders else pl.DataFrame()
        logger.info(f"Extracted {len(tenders)} tenders")
        return df

    def extract_companies(self, ocds_data: dict) -> pl.DataFrame:
        """Extract company nodes (winners) from OCDS data."""
        companies = []
        seen_cfs = set()

        items = self._extract_releases(ocds_data)

        for release in items:
            # Extract from awards
            for award in release.get("awards", []):
                for supplier in award.get("suppliers", []):
                    cf = supplier.get("id", "").strip()

                    if not cf or cf in seen_cfs:
                        continue

                    seen_cfs.add(cf)

                    company = {
                        "id": self._generate_uuid(),
                        "cf": cf,
                        "piva": self._extract_piva(cf),
                        "nome_normalizzato": CompanyNormalizer.normalize(supplier.get("name", "")),
                        "nome_originale": supplier.get("name", ""),
                        "source": [self.source],
                        "dataset_version": self.dataset_version,
                        "retrieval_date": self.retrieval_date,
                        "confidence": 0.95,
                    }

                    companies.append(company)

        df = pl.DataFrame(companies) if companies else pl.DataFrame()
        logger.info(f"Extracted {len(companies)} unique companies")
        return df

    def extract_buyers(self, ocds_data: dict) -> pl.DataFrame:
        """Extract buyer nodes from OCDS data."""
        buyers = []
        seen_cfs = set()

        items = self._extract_releases(ocds_data)

        for release in items:
            # Extract buyer from parties
            for party in release.get("parties", []):
                if "buyer" in party.get("roles", []):
                    cf = party.get("id", "").strip()

                    if not cf or cf in seen_cfs:
                        continue

                    seen_cfs.add(cf)

                    buyer = {
                        "id": self._generate_uuid(),
                        "cf": cf,
                        "nome": party.get("name", ""),
                        "tipo": party.get("classification", {}).get("description", ""),
                        "source": self.source,
                    }

                    buyers.append(buyer)

        df = pl.DataFrame(buyers) if buyers else pl.DataFrame()
        logger.info(f"Extracted {len(buyers)} unique buyers")
        return df

    def extract_wins(self, ocds_data: dict) -> pl.DataFrame:
        """Extract WINS relationships from OCDS data."""
        wins = []

        items = self._extract_releases(ocds_data)

        for release in items:
            id_val = release.get("ocid") or release.get("id", "")
            tender_cig = id_val.split("-")[-1].split("/")[0] if id_val else ""

            for award in release.get("awards", []):
                award_date = self._extract_date(award.get("date"))
                award_amount = self._extract_amount(award.get("value", {}))

                for supplier in award.get("suppliers", []):
                    cf = supplier.get("id", "").strip()

                    if not cf or not tender_cig:
                        continue

                    win = {
                        "company_cf": cf,
                        "tender_cig": tender_cig,
                        "data": award_date,
                        "importo": award_amount,
                        "source": self.source,
                        "confidence": 0.95,
                    }

                    wins.append(win)

        df = pl.DataFrame(wins) if wins else pl.DataFrame()
        logger.info(f"Extracted {len(wins)} WINS relationships")
        return df

    # Utility methods

    def _generate_uuid(self) -> str:
        """Generate a UUID for a node."""
        import uuid

        return str(uuid.uuid4())

    def _extract_amount(self, value_obj: dict) -> float | None:
        """Extract amount from OCDS value object."""
        amount = value_obj.get("amount")
        if amount is not None:
            try:
                return float(amount)
            except (ValueError, TypeError):
                return None
        return None

    def _extract_date(self, date_str: str | None) -> str | None:
        """Extract and validate ISO date string."""
        if not date_str:
            return None

        try:
            # Validate ISO format
            datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return date_str
        except (ValueError, AttributeError):
            return None

    def _extract_piva(self, cf: str) -> str | None:
        """Extract PIVA from CF if it's a VAT number."""
        # Italian VAT numbers are 11 digits starting with IT
        if cf.startswith("IT") and len(cf) == 13 and cf[2:].isdigit():
            return cf

        # Or just 11 digits
        if len(cf) == 11 and cf.isdigit():
            return f"IT{cf}"

        return None

    def _normalize_name(self, name: str) -> str:
        """Helper for unit tests."""
        return CompanyNormalizer.normalize(name)
