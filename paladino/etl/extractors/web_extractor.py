import importlib
import os

import requests

from paladino.etl.unstructured_models import ExtractedDocument


class WebExtractor:
    """Extractor for web pages via URL."""

    def extract(self, source: str) -> ExtractedDocument:
        content = self._extract_trafilatura(source)
        method = "trafilatura"

        if not content:
            content = self._extract_jina_reader(source)
            method = "jina-reader"

        if not content and os.getenv("FIRECRAWL_API_KEY"):
            content = self._extract_firecrawl(source)
            method = "firecrawl"

        if not content:
            raise ValueError(
                "Unable to extract readable content from URL via Trafilatura, "
                "Jina Reader, or Firecrawl fallback"
            )

        return ExtractedDocument(
            source=source,
            source_type="web",
            title=source,
            content=content,
            extraction_method=method,
        )

    @staticmethod
    def _extract_trafilatura(source: str) -> str:
        try:
            trafilatura = importlib.import_module("trafilatura")
        except ImportError:
            return ""

        downloaded = trafilatura.fetch_url(source)
        if not downloaded:
            return ""

        content = trafilatura.extract(downloaded, include_links=True, output_format="markdown")
        return (content or "").strip()

    @staticmethod
    def _extract_jina_reader(source: str) -> str:
        # Public fallback without API key: https://r.jina.ai/http://target
        url = f"https://r.jina.ai/http://{source.replace('https://', '').replace('http://', '')}"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.text.strip()
        except Exception:
            return ""

    @staticmethod
    def _extract_firecrawl(source: str) -> str:
        api_key = os.getenv("FIRECRAWL_API_KEY")
        if not api_key:
            return ""

        try:
            response = requests.post(
                "https://api.firecrawl.dev/v1/scrape",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "url": source,
                    "formats": ["markdown"],
                },
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", {})
            return str(data.get("markdown", "")).strip()
        except Exception:
            return ""
