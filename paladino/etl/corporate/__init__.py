"""
Corporate structure ETL sub-package.

Loads board-member, shareholder, and ownership data into the graph as
Person nodes with REPRESENTS / SHAREHOLDER_OF / SHARES_UBO edges.

Supported data sources (in priority order):
  1. data/corporate/raw/*.csv  — any CSV dropped by the user (schema auto-detected)
  2. data/pnnr/PNRR_Soggetti.csv  — extracts role assignments already loaded
  3. ATOKA commercial API  — pass ATOKA_API_KEY env-var to activate
  4. Registro Imprese / ANAC OpenData  — auto-fetched by RegistroImpreseFetcher

Incremental-sync tracking (SyncCheckpoint nodes in Neo4j):
  Use CorporateSyncTracker to record and query ETL run timestamps,
  enabling delta-only reprocessing.

See paladino/etl/corporate/download.py for detailed format documentation.
See paladino/etl/corporate/infocamere_downloader.py for fetch details.
"""

from paladino.etl.corporate.download import CorporateSourceDiscovery
from paladino.etl.corporate.transform import CorporateTransformer
from paladino.etl.corporate.load import CorporateLoader
from paladino.etl.corporate.infocamere_downloader import RegistroImpreseFetcher
from paladino.etl.corporate.incremental_sync import CorporateSyncTracker

__all__ = [
    "CorporateSourceDiscovery",
    "CorporateTransformer",
    "CorporateLoader",
    "RegistroImpreseFetcher",
    "CorporateSyncTracker",
]
