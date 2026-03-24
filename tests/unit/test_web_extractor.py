from paladino.etl.extractors.web_extractor import WebExtractor


def test_web_extractor_uses_jina_when_trafilatura_empty(monkeypatch):
    monkeypatch.setattr(WebExtractor, "_extract_trafilatura", staticmethod(lambda source: ""))
    monkeypatch.setattr(WebExtractor, "_extract_jina_reader", staticmethod(lambda source: "content from jina"))

    extractor = WebExtractor()
    result = extractor.extract("https://example.com")

    assert result.content == "content from jina"
    assert result.extraction_method == "jina-reader"


def test_web_extractor_uses_firecrawl_when_others_fail(monkeypatch):
    monkeypatch.setattr(WebExtractor, "_extract_trafilatura", staticmethod(lambda source: ""))
    monkeypatch.setattr(WebExtractor, "_extract_jina_reader", staticmethod(lambda source: ""))
    monkeypatch.setattr(WebExtractor, "_extract_firecrawl", staticmethod(lambda source: "content from firecrawl"))
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")

    extractor = WebExtractor()
    result = extractor.extract("https://example.com")

    assert result.content == "content from firecrawl"
    assert result.extraction_method == "firecrawl"
