"""
Company name normalization utilities.
"""

import re


class CompanyNameNormalizer:
    """Normalize company names for matching."""

    # Legal suffixes to remove
    LEGAL_SUFFIXES = [
        r"\bS\.R\.L\.S?\b",
        r"\bSRL\.?S?\b",
        r"\bS\.P\.A\.\b",
        r"\bSPA\.?\b",
        r"\bS\.N\.C\.\b",
        r"\bSNC\.?\b",
        r"\bS\.A\.S\.\b",
        r"\bSAS\.?\b",
        r"\bS\.S\.\b",
        r"\bSS\.?\b",
        r"\bSOC\.?\s+COOP\.?\b",
        r"\bCOOPERATIVA\b",
        r"\bCONSORZIO\b",
        r"\bASSOCIAZIONE\b",
        r"\bFONDAZIONE\b",
    ]

    # Common abbreviations
    ABBREVIATIONS = {
        "COSTRUZIONI": "COSTR",
        "INGEGNERIA": "ING",
        "SERVIZI": "SERV",
        "GENERALE": "GEN",
        "ITALIANA": "ITAL",
        "NAZIONALE": "NAZ",
        "INTERNAZIONALE": "INTERN",
        "TECNOLOGIE": "TECN",
        "INFORMATICA": "INFO",
    }

    def normalize(self, name: str) -> str:
        """
        Normalize a company name.

        Args:
            name: Raw company name

        Returns:
            Normalized name
        """
        if not name:
            return ""

        # Uppercase
        normalized = name.upper().strip()

        # Remove dots (common in S.R.L., A.C.M.E.)
        normalized = normalized.replace(".", "")

        # Remove legal suffixes
        for suffix in self.LEGAL_SUFFIXES:
            # We need to escape dots in suffixes if they weren't removed,
            # but since we removed dots above, we should adjust suffixes or handle both.
            # Most suffixes in LEGAL_SUFFIXES use \. which won't match anymore.
            # I'll strip dots from suffixes too for the match.
            clean_suffix = suffix.replace("\\.", "")
            normalized = re.sub(clean_suffix, " ", normalized, flags=re.IGNORECASE)

        # Remove other punctuation except spaces
        normalized = re.sub(r"[^\w\s]", " ", normalized)

        # Collapse multiple spaces
        normalized = re.sub(r"\s+", " ", normalized).strip()

        return normalized

    def normalize_aggressive(self, name: str) -> str:
        """
        Aggressive normalization for fuzzy matching.

        Args:
            name: Raw company name

        Returns:
            Aggressively normalized name
        """
        normalized = self.normalize(name)

        # Apply abbreviations
        for full, abbr in self.ABBREVIATIONS.items():
            normalized = normalized.replace(full, abbr)

        # Remove common words
        stop_words = ["DI", "E", "IL", "LA", "DEL", "DELLA", "PER"]
        words = normalized.split()
        words = [w for w in words if w not in stop_words]

        return " ".join(words)

    def extract_core_name(self, name: str) -> str:
        """
        Extract core name (first 3-4 significant words).

        Args:
            name: Raw company name

        Returns:
            Core name for blocking
        """
        normalized = self.normalize(name)
        words = normalized.split()

        # Take first 3 words (or fewer if shorter)
        core_words = words[: min(3, len(words))]

        return " ".join(core_words)
