from pathlib import Path

import requests

from paladino.config import settings
from paladino.etl.unstructured_models import ExtractedDocument


class AudioExtractor:
    """Extractor for audio sources using local faster-whisper or API fallback."""

    def __init__(
        self,
        local_model: str = "small",
        language: str = "it",
        use_api_fallback: bool = True,
    ) -> None:
        self.local_model = local_model
        self.language = language
        self.use_api_fallback = use_api_fallback

    def extract(self, source: Path | str) -> ExtractedDocument:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Audio source does not exist: {source}")

        try:
            text = self._extract_local(path)
            method = f"faster-whisper:{self.local_model}"
        except Exception:
            if not self.use_api_fallback:
                raise
            text = self._extract_api(path)
            method = "openai-whisper-api"

        if not text.strip():
            raise ValueError(f"No transcription generated for audio source: {path}")

        return ExtractedDocument(
            source=str(path),
            source_type="audio",
            title=path.stem,
            content=text,
            extraction_method=method,
        )

    def _extract_local(self, path: Path) -> str:
        from faster_whisper import WhisperModel

        model = WhisperModel(self.local_model, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(path), language=self.language)
        return "\n".join(segment.text.strip() for segment in segments if segment.text).strip()

    @staticmethod
    def _extract_api(path: Path) -> str:
        if not settings.llm_api_key:
            raise RuntimeError("LLM API key is not configured for API fallback transcription")

        base = settings.llm_api_base or "https://api.openai.com/v1"
        url = f"{base.rstrip('/')}/audio/transcriptions"

        with open(path, "rb") as audio_file:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                files={"file": (path.name, audio_file, "application/octet-stream")},
                data={"model": "whisper-1"},
                timeout=120,
            )

        response.raise_for_status()
        payload = response.json()
        return str(payload.get("text", "")).strip()
