import csv
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from paladino.etl.connection_resolver import ConnectionResolver
from paladino.etl.extractors import AudioExtractor, PDFExtractor, TextExtractor, WebExtractor
from paladino.etl.unstructured_models import ConnectionReport, ExtractedDocument, NERResult


@dataclass
class RoutingDecision:
    """Routing outcome for a given source."""

    source: str
    route: str
    reason: str
    handler: str
    next_command: str | None = None


class UniversalIngestor:
    """
    Smart ingestion router.

    Important: this ingestor is for unstructured or semi-structured sources.
    Known structured public datasets (ANAC/OpenCUP/ISTAT/PNRR) should continue
    to use the dedicated ETL pipelines already present in Paladino.
    """

    KNOWN_STRUCTURED_SIGNATURES = {
        "opencup": {"CUP", "DESCRIZIONE_SINTETICA_CUP", "TITOLO_PROGETTO"},
        "pnrr": {"CUP", "CIG", "Missione", "Componente"},
        "istat": {"Codice Regione", "Provincia", "Popolazione"},
        "anac": {"ocid", "releases", "awards", "tender"},
    }

    STRUCTURED_ETL_SCRIPT_MAP = {
        "anac": "scripts/run_anac_etl.py",
        "opencup": "scripts/run_opencup_etl.py",
        "istat": "scripts/run_istat_etl.py",
        "pnrr": "scripts/run_pnnr_etl.py",
    }

    def __init__(self) -> None:
        self._audio_extractor = AudioExtractor()
        self._pdf_extractor = PDFExtractor()
        self._text_extractor = TextExtractor()
        self._web_extractor = WebExtractor()
        # Lazy-init for resolver (needs db + llm)
        self._resolver: ConnectionResolver | None = None

    def _get_resolver(self, llm_manager=None) -> ConnectionResolver:
        """Lazily create the connection resolver."""
        if self._resolver is None:
            from paladino.db import Neo4jConnection
            from paladino.config import settings

            db = Neo4jConnection(
                settings.neo4j_uri,
                settings.neo4j_user,
                settings.neo4j_password,
            )
            self._resolver = ConnectionResolver(db=db, llm_manager=llm_manager)
        return self._resolver

    def route(self, source: str) -> RoutingDecision:
        if self._is_url(source):
            return RoutingDecision(
                source=source,
                route="unstructured",
                reason="URL source requires web text extraction",
                handler="web_extractor",
            )

        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Source does not exist: {source}")

        known_dataset = self._detect_known_structured_source(path)
        if known_dataset:
            script = self.STRUCTURED_ETL_SCRIPT_MAP.get(known_dataset)
            return RoutingDecision(
                source=source,
                route="structured",
                reason=f"Detected known structured dataset signature: {known_dataset}",
                handler=f"existing_{known_dataset}_etl",
                next_command=script,
            )

        suffix = path.suffix.lower()
        if suffix == ".csv":
            return RoutingDecision(
                source=source,
                route="structured",
                reason="CSV detected but no known signature; route to structured/custom ingest",
                handler="custom_csv_import",
            )

        if suffix == ".pdf":
            return RoutingDecision(
                source=source,
                route="unstructured",
                reason="PDF detected",
                handler="pdf_extractor",
            )

        if suffix in {".mp3", ".wav", ".m4a", ".ogg", ".flac"}:
            return RoutingDecision(
                source=source,
                route="unstructured",
                reason="Audio source detected",
                handler="audio_extractor",
            )

        if suffix in {".txt", ".md", ".markdown", ".html", ".htm"}:
            return RoutingDecision(
                source=source,
                route="unstructured",
                reason="Text-like document detected",
                handler="text_extractor",
            )

        return RoutingDecision(
            source=source,
            route="unstructured",
            reason="Unknown extension; falling back to text extraction",
            handler="text_extractor",
        )

    def import_csv(
        self,
        source: str,
        column_map: dict | None = None,
        node_type: str | None = None,
        dry_run: bool = False,
    ):
        """
        Import an arbitrary CSV file into the Neo4j graph.

        Returns a :class:`~paladino.etl.csv_importer.ImportResult` dataclass.
        This is the preferred entry-point for Feature 5.3 (CSV / Custom Data Import).
        """
        from paladino.etl.csv_importer import CustomCSVImporter

        decision = self.route(source)
        if decision.handler != "custom_csv_import":
            raise ValueError(
                f"'{source}' was not routed to the CSV importer "
                f"(handler={decision.handler!r}, route={decision.route!r}). "
                "Pass a plain CSV whose headers do not match any known dataset signature."
            )
        importer = CustomCSVImporter()
        return importer.import_file(
            Path(source),
            column_map_override=column_map,
            node_type_override=node_type,
            dry_run=dry_run,
        )

    def ingest(self, source: str) -> ExtractedDocument:
        decision = self.route(source)
        if decision.route == "structured" and decision.handler != "custom_csv_import":
            raise ValueError(
                "Source is a known structured dataset. "
                "Use dedicated ETL scripts instead of UniversalIngestor. "
                f"Routing hint: {decision.handler}. "
                f"Suggested command: {decision.next_command or 'n/a'}"
            )
        if decision.handler == "custom_csv_import":
            raise ValueError("This source is an unknown CSV. Use import_csv() instead of ingest().")

        if decision.handler == "web_extractor":
            return self._web_extractor.extract(source)

        if decision.handler == "pdf_extractor":
            return self._pdf_extractor.extract(source)

        if decision.handler == "audio_extractor":
            return self._audio_extractor.extract(source)

        return self._text_extractor.extract(source)

    @staticmethod
    def _is_url(source: str) -> bool:
        parsed = urlparse(source)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _detect_known_structured_source(self, path: Path) -> str | None:
        filename = path.name.lower()
        if "opencup" in filename:
            return "opencup"
        if "anac" in filename or filename.endswith(".json"):
            if self._json_contains_keys(path, self.KNOWN_STRUCTURED_SIGNATURES["anac"]):
                return "anac"
        if "istat" in filename:
            return "istat"
        if "pnrr" in filename or "pnnr" in filename:
            return "pnrr"

        if path.suffix.lower() == ".csv":
            headers = self._read_csv_headers(path)
            for dataset, signature in self.KNOWN_STRUCTURED_SIGNATURES.items():
                if headers & signature:
                    return dataset

        return None

    @staticmethod
    def _read_csv_headers(path: Path) -> set[str]:
        raw = path.read_text(encoding="utf-8-sig", errors="ignore")
        lines = raw.splitlines()
        if not lines:
            return set()

        sample = "\n".join(lines[:3])
        delimiter = ","
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ";" if ";" in lines[0] else ","

        return {item.strip().strip('"') for item in lines[0].split(delimiter)}

    @staticmethod
    def _json_contains_keys(path: Path, expected_keys: set[str]) -> bool:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        sample = raw[:8000]
        return any(f'"{key}"' in sample for key in expected_keys)

    # ──────────────────────────────────────────────────────────────
    # Connection-aware ingestion
    # ──────────────────────────────────────────────────────────────

    def ingest_with_connections(
        self,
        source: str,
        ner_pipeline=None,
        llm_manager=None,
    ) -> ConnectionReport:
        """
        Ingest an unstructured source, extract entities/relationships, and resolve
        them against the existing Neo4j graph.

        Args:
            source: File path, URL, or known dataset path
            ner_pipeline: UnstructuredNERPipeline instance (created if None)
            llm_manager: LLMManager instance for NER + LLM judge (created if None)

        Returns:
            ConnectionReport with match/create counts and discovered connections
        """
        # Step 1: Route and extract
        decision = self.route(source)
        if decision.route == "structured" and decision.handler != "custom_csv_import":
            raise ValueError(
                f"Source '{source}' is a known structured dataset. "
                f"Use dedicated ETL scripts instead. Hint: {decision.handler}"
            )
        if decision.handler == "custom_csv_import":
            raise ValueError("Use import_csv() for CSV sources, not ingest_with_connections().")

        doc = self.ingest(source)

        # Step 2: Run NER pipeline if not provided
        if ner_pipeline is None:
            from paladino.etl.ner_pipeline import UnstructuredNERPipeline
            from paladino.llm_manager import LLMManager

            llm = llm_manager or LLMManager()
            ner_pipeline = UnstructuredNERPipeline(llm_manager=llm)

        ner_result = ner_pipeline.extract(doc)

        # Step 3: Resolve connections
        resolver = self._get_resolver(llm_manager=ner_pipeline.llm)
        report = resolver.resolve(ner_result, source=source)

        return report
