from pathlib import Path
from io import BytesIO

from paladino.etl.unstructured_models import ExtractedDocument


class PDFExtractor:
    """Extractor for PDF documents using local libraries."""

    def extract(self, source: Path | str) -> ExtractedDocument:
        path = Path(source)
        text, method = self._extract_with_pymupdf(path)
        return ExtractedDocument(
            source=str(path),
            source_type="pdf",
            title=path.stem,
            content=text,
            extraction_method=method,
        )

    def _extract_with_pymupdf(self, path: Path) -> tuple[str, str]:
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError(
                "PyMuPDF is required for PDF extraction. Install with: pip install pymupdf"
            ) from exc

        chunks: list[str] = []
        with fitz.open(path) as doc:
            for page in doc:
                chunks.append(page.get_text("text"))

        text = "\n".join(chunks).strip()
        if text:
            return text, "pymupdf"

        ocr_text = self._extract_with_ocr(path)
        if not ocr_text:
            raise ValueError(f"No text could be extracted from PDF: {path}")
        return ocr_text, "pymupdf+ocr"

    def _extract_with_ocr(self, path: Path) -> str:
        try:
            import fitz
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError(
                "OCR fallback requires pytesseract and pillow. Install with: "
                "pip install pytesseract pillow"
            ) from exc

        chunks: list[str] = []
        with fitz.open(path) as doc:
            for page in doc:
                pix = page.get_pixmap(alpha=False)
                image = Image.open(BytesIO(pix.tobytes("png")))
                text = pytesseract.image_to_string(image, lang="ita+eng")
                if text:
                    chunks.append(text)
        return "\n".join(chunks).strip()
