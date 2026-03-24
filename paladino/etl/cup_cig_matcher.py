from datetime import datetime


class CupCigMatcher:
    """Matches Tenders (CIG) to Projects (CUP) using multiple strategies."""

    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold

    def match(self, tender: dict, projects: list[dict]) -> list[dict]:
        """
        Find potential project matches for a single tender.

        Returns a list of matches with confidence scores.
        """
        matches = []

        for project in projects:
            score = 0.0
            reasons = []

            # 1. Explicit Matching (CIG explicitly mentions CUP in description)
            if project["cup"] in tender.get("oggetto", ""):
                score = 1.0
                reasons.append("explicit_mention")

            # 2. Temporal Matching
            if score < 1.0:
                temp_score = self._calculate_temporal_score(tender, project)
                if temp_score > 0:
                    score += temp_score * 0.4
                    reasons.append("temporal_overlap")

            # 3. Semantic Overlap (Keyword matching)
            if score < 1.0:
                semantic_score = self._calculate_semantic_score(tender, project)
                if semantic_score > self.threshold:
                    score += semantic_score * 0.6
                    reasons.append("semantic_similarity")

            if score >= self.threshold:
                matches.append(
                    {
                        "tender_cig": tender["cig"],
                        "project_cup": project["cup"],
                        "confidence": min(score, 1.0),
                        "matching_method": "|".join(reasons),
                        "match_date": datetime.now().isoformat(),
                    }
                )

        return sorted(matches, key=lambda x: x["confidence"], reverse=True)

    def _calculate_temporal_score(self, tender: dict, project: dict) -> float:
        """Checks if tender dates align with project dates."""
        t_date = tender.get("data_aggiudicazione") or tender.get("data_apertura")
        p_start = project.get("data_inizio")
        p_end = project.get("data_fine")

        if not t_date or not p_start:
            return 0.0

        # Very simple check: is tender date after project start?
        if t_date >= p_start:
            if not p_end or t_date <= p_end:
                return 1.0
        return 0.0

    def _calculate_semantic_score(self, tender: dict, project: dict) -> float:
        """Simple Jaccard similarity between tender object and project title."""
        t_words = set(tender.get("oggetto", "").upper().split())
        p_words = set(project.get("titolo", "").upper().split())

        # Remove small stop words
        t_words = {w for w in t_words if len(w) > 3}
        p_words = {w for w in p_words if len(w) > 3}

        if not t_words or not p_words:
            return 0.0

        intersection = t_words.intersection(p_words)
        union = t_words.union(p_words)

        return len(intersection) / len(union)
