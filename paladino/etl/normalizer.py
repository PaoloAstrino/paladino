import re


class CompanyNormalizer:
    """Advanced normalization for Italian company names."""

    # Common Italian legal form suffixes (ordered by length descending for greedy matching)
    LEGAL_FORMS = [
        "SOCIETA' A RESPONSABILITA' LIMITATA SEMPLIFICATA",
        "SOCIETA' A RESPONSABILITA' LIMITATA",
        "SOCIETA' PER AZIONI",
        "SOCIETA' COOPERATIVA",
        "SOCIETA' CONSORTILE",
        "SOCIETA' SEMPLICE",
        "S.C.A.R.L.S.",
        "S.C.A.R.L.",
        "S.R.L.S.",
        "S.P.A.",
        "S.R.L.",
        "S.N.C.",
        "S.A.S.",
        "SCARLS",
        "SCARL",
        "SRLS",
        "SRL",
        "SNC",
        "SAS",
        "S.S.",
        "S R L",
    ]

    @classmethod
    def normalize(cls, name: str) -> str:
        """
        Normalize an Italian company name.

        Args:
            name: Original company name string

        Returns:
            Normalized name (uppercase, no legal forms, cleaned whitespace)
        """
        if not name:
            return ""

        # 1. To uppercase and strip
        normalized = name.upper().strip()

        # 2. Greedy removal of legal forms BEFORE punctuation removal
        changed = True
        while changed:
            changed = False
            for form in cls.LEGAL_FORMS:
                # Pattern for form at the end (case insensitive due to upper() above)
                pattern = rf"\b{re.escape(form)}\.?$"
                new_val = re.sub(pattern, "", normalized).strip()
                if new_val != normalized:
                    normalized = new_val
                    changed = True
                    break

        # 3. Handle accented characters and apostrophes
        normalized = normalized.replace("À", "A").replace("È", "E").replace("É", "E")
        normalized = normalized.replace("Ì", "I").replace("Ò", "O").replace("Ù", "U")
        normalized = normalized.replace("'", " ")

        # 4. Remove common punctuation
        normalized = re.sub(r"[^\w\s]", " ", normalized)

        # 5. Final cleanup of legal forms after punctuation removal
        # (in case they were S.R.L. and became S R L)
        changed = True
        while changed:
            changed = False
            for form in [
                "SRL",
                "SPA",
                "SNC",
                "SAS",
                "SCARL",
                "SCARLS",
                "SRLS",
                "SOCIETA COOPERATIVA",
            ]:
                pattern = rf"\b{form}$"
                new_val = re.sub(pattern, "", normalized).strip()
                if new_val != normalized:
                    normalized = new_val
                    changed = True
                    break

        # 6. Final whitespace collapse
        normalized = re.sub(r"\s+", " ", normalized).strip()

        return normalized

    @classmethod
    def get_core_name(cls, name: str) -> str:
        """Extract the core name, removing everything except letters and numbers."""
        normalized = cls.normalize(name)
        # Remove anything that isn't alphanumeric
        core = re.sub(r"[^A-Z0-9]", "", normalized)
        return core

    @classmethod
    def get_phonetic_key(cls, name: str) -> str:
        """
        Generates an Italian-optimized phonetic key.
        Groups 'Acme' and 'Akme' or 'Cielo' and 'Kielo'.
        """
        normalized = cls.normalize(name)
        if not normalized:
            return ""

        # 1. Basic Italian Phonetic Mapping
        text = normalized
        text = text.replace("GN", "N").replace("GLI", "L")
        text = re.sub(r"[C|G|Q|K]", "K", text)
        text = text.replace("PH", "F")

        # 2. Remove vowels
        text = "".join([c for c in text if c not in "AEIOU"])

        # 3. Collapse double letters
        text = re.sub(r"(.)\1+", r"\1", text)

        return text[:8]  # First 8 phonetic chars

    @classmethod
    def get_blocking_key(cls, name: str, istat_code: str | None = None) -> str:
        """
        Generates a composite blocking key.
        If ISTAT is provided, creates a geo-constrained block.
        """
        phonetic = cls.get_phonetic_key(name)
        if istat_code:
            return f"{istat_code}_{phonetic[:4]}"
        return phonetic[:6]
