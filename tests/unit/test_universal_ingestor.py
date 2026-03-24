from pathlib import Path

import pytest

from paladino.etl.universal_ingestor import UniversalIngestor


def test_route_url_uses_web_extractor() -> None:
    ingestor = UniversalIngestor()
    decision = ingestor.route("https://example.gov.it/notizia")

    assert decision.route == "unstructured"
    assert decision.handler == "web_extractor"


def test_route_known_pnrr_csv_to_existing_pipeline(tmp_path: Path) -> None:
    source = tmp_path / "PNRR_Soggetti.csv"
    source.write_text("CUP;Missione;Componente\nABC123;M1;C1\n", encoding="utf-8")

    ingestor = UniversalIngestor()
    decision = ingestor.route(str(source))

    assert decision.route == "structured"
    assert decision.handler == "existing_pnrr_etl"
    assert decision.next_command == "scripts/run_pnnr_etl.py"


def test_route_unknown_csv_to_custom_structured_import(tmp_path: Path) -> None:
    source = tmp_path / "custom.csv"
    source.write_text("foo,bar\na,b\n", encoding="utf-8")

    ingestor = UniversalIngestor()
    decision = ingestor.route(str(source))

    assert decision.route == "structured"
    assert decision.handler == "custom_csv_import"


def test_route_text_file_to_text_extractor(tmp_path: Path) -> None:
    source = tmp_path / "memo.txt"
    source.write_text("hello world", encoding="utf-8")

    ingestor = UniversalIngestor()
    decision = ingestor.route(str(source))

    assert decision.route == "unstructured"
    assert decision.handler == "text_extractor"


def test_route_audio_file_to_audio_extractor(tmp_path: Path) -> None:
    source = tmp_path / "meeting_audio.mp3"
    source.write_bytes(b"fake-audio-bytes")

    ingestor = UniversalIngestor()
    decision = ingestor.route(str(source))

    assert decision.route == "unstructured"
    assert decision.handler == "audio_extractor"


def test_ingest_raises_on_known_structured_source(tmp_path: Path) -> None:
    source = tmp_path / "OpenCUP_Projects.csv"
    source.write_text("CUP,DESCRIZIONE_SINTETICA_CUP\nA,Test\n", encoding="utf-8")

    ingestor = UniversalIngestor()

    with pytest.raises(ValueError, match="dedicated ETL"):
        ingestor.ingest(str(source))
