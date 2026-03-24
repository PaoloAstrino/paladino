from paladino.etl.cup_cig_matcher import CupCigMatcher


def test_explicit_match():
    matcher = CupCigMatcher()
    tender = {"cig": "CIG123", "oggetto": "Lavori per CUP456 in centro"}
    projects = [{"cup": "CUP456", "titolo": "Progetto Piazza"}]

    matches = matcher.match(tender, projects)
    assert len(matches) == 1
    assert matches[0]["project_cup"] == "CUP456"
    assert matches[0]["confidence"] == 1.0


def test_semantic_match():
    matcher = CupCigMatcher(threshold=0.3)
    # Overlap: "RISTRUTTURAZIONE", "SCUOLA", "MATERNA"
    tender = {"cig": "CIG789", "oggetto": "Ristrutturazione straordinaria scuola materna Marconi"}
    projects = [{"cup": "CUP999", "titolo": "Ristrutturazione scuola materna"}]

    matches = matcher.match(tender, projects)
    assert len(matches) == 1
    assert matches[0]["confidence"] >= 0.3


def test_no_match():
    matcher = CupCigMatcher()
    tender = {"cig": "CIG000", "oggetto": "Fornitura carta ufficio"}
    projects = [{"cup": "CUP111", "titolo": "Costruzione Ponte"}]

    matches = matcher.match(tender, projects)
    assert len(matches) == 0
