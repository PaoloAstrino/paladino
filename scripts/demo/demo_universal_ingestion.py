#!/usr/bin/env python3
"""
Demo script for the Universal Ingestion Engine.

Usage:
    python scripts/demo_universal_ingestion.py --source path/to/document.pdf
    python scripts/demo_universal_ingestion.py --source https://example.gov.it/page --to-neo4j
    python scripts/demo_universal_ingestion.py --source path/to/long.txt --max-chars 8000 --chunk-overlap 300
"""

import argparse
import json
import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from paladino.etl.universal_ingestor import UniversalIngestor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Universal ingestion demo")
    parser.add_argument("--source", required=True, help="Path or URL to ingest")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=12000,
        help="Max characters per LLM chunk (default: 12000)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=400,
        help="Overlap between chunks in characters (default: 400)",
    )
    parser.add_argument(
        "--to-neo4j",
        action="store_true",
        help="Load extracted entities into Neo4j",
    )
    args = parser.parse_args()

    if args.max_chars <= 0:
        parser.error("--max-chars must be > 0")
    if args.chunk_overlap < 0:
        parser.error("--chunk-overlap must be >= 0")
    if args.chunk_overlap >= args.max_chars:
        parser.error("--chunk-overlap must be smaller than --max-chars")

    return args


def main() -> None:
    args = parse_args()

    ingestor = UniversalIngestor()
    decision = ingestor.route(args.source)

    logger.info(f"Routing decision: {decision.route} ({decision.reason}) -> {decision.handler}")
    if decision.route == "structured":
        message = (
            "Detected known structured source. Use dedicated ETL scripts instead "
            f"(hint: {decision.handler})"
        )
        if decision.next_command:
            message += f". Suggested script: {decision.next_command}"
        logger.warning(message)
        return

    document = ingestor.ingest(args.source)
    logger.info(f"Extracted content from {document.source_type}: {document.source}")

    from paladino.etl.ner_pipeline import UnstructuredNERPipeline

    pipeline = UnstructuredNERPipeline(
        max_chars_per_chunk=args.max_chars,
        chunk_overlap=args.chunk_overlap,
    )
    ner_result = pipeline.extract(document)

    print(json.dumps(ner_result.model_dump(), indent=2, ensure_ascii=False))

    if args.to_neo4j:
        from paladino.etl.unstructured_loader import UnstructuredGraphLoader

        loader = UnstructuredGraphLoader()
        stats = loader.load(document, ner_result)
        logger.success(f"Loaded to Neo4j: {stats}")


if __name__ == "__main__":
    main()
