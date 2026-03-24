from pathlib import Path

from paladino.etl.unstructured_models import ExtractedDocument


class TextExtractor:
    """Extractor for plain text and markdown files."""

    def extract(self, source: Path | str) -> ExtractedDocument:
        path = Path(source)
        content = path.read_text(encoding="utf-8", errors="ignore")
        source_type = "markdown" if path.suffix.lower() in {".md", ".markdown"} else "text"
        return ExtractedDocument(
            source=str(path),
            source_type=source_type,
            title=path.stem,
            content=content,
            extraction_method="native_text_reader",
        )
