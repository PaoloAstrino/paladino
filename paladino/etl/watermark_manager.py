"""
Watermark Manager for Incremental ETL.

Tracks the last processed timestamp/ID for each data source,
enabling incremental loading of only new/updated records.

Usage:
    from paladino.etl.watermark_manager import WatermarkManager
    
    wm = WatermarkManager(driver)
    
    # Get last watermark
    last_timestamp = wm.get_watermark("anac_tenders")
    
    # Fetch only new data
    new_data = fetch_tenders(since=last_timestamp)
    
    # Process and load
    load_to_neo4j(new_data)
    
    # Update watermark
    wm.save_watermark("anac_tenders", new_max_timestamp)
"""

from datetime import datetime
from typing import Any

from loguru import logger

from paladino.db import Neo4jConnection


class WatermarkManager:
    """
    Manage ETL watermarks for incremental data loading.
    
    Watermarks are stored in Neo4j as:
    (:Watermark {source: 'anac_tenders', last_value: '2026-01-15', last_id: 12345})
    """
    
    def __init__(self, driver: Neo4jConnection | None = None):
        """
        Initialize watermark manager.
        
        Args:
            driver: Neo4j connection (uses default if None)
        """
        if driver is None:
            from paladino.db import get_driver
            self.driver = get_driver()
        else:
            self.driver = driver
    
    def get_watermark(self, source: str) -> dict[str, Any]:
        """
        Get watermark for a data source.
        
        Args:
            source: Source identifier (e.g., 'anac_tenders', 'openCUP_projects')
            
        Returns:
            Dict with watermark values:
            - last_value: Last processed value (timestamp, ID, etc.)
            - last_id: Last processed ID (if applicable)
            - updated_at: When watermark was last updated
            - rows_processed: Total rows processed for this source
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (w:Watermark {source: $source})
                RETURN w.last_value AS last_value,
                       w.last_id AS last_id,
                       w.updated_at AS updated_at,
                       w.rows_processed AS rows_processed
                LIMIT 1
            """, source=source)
            
            record = result.single()
            
            if record is None:
                # No watermark exists - return defaults for full load
                return {
                    "last_value": None,
                    "last_id": None,
                    "updated_at": None,
                    "rows_processed": 0,
                }
            
            return {
                "last_value": record["last_value"],
                "last_id": record["last_id"],
                "updated_at": record["updated_at"],
                "rows_processed": record["rows_processed"] or 0,
            }
    
    def save_watermark(
        self,
        source: str,
        last_value: Any,
        last_id: int | None = None,
        rows_processed: int | None = None,
        incremental_rows: int = 0,
    ) -> None:
        """
        Save/update watermark for a data source.
        
        Args:
            source: Source identifier
            last_value: Last processed value (timestamp, ID, etc.)
            last_id: Last processed ID (if applicable)
            rows_processed: Total rows processed (cumulative)
            incremental_rows: Rows processed in this batch
        """
        with self.driver.session() as session:
            # Get current watermark to calculate cumulative rows
            current = self.get_watermark(source)
            
            if rows_processed is None:
                # Add incremental to existing
                total_rows = current["rows_processed"] + incremental_rows
            else:
                # Use provided value
                total_rows = rows_processed
            
            session.run("""
                MERGE (w:Watermark {source: $source})
                SET w.last_value = $last_value,
                    w.last_id = $last_id,
                    w.rows_processed = $rows_processed,
                    w.updated_at = datetime()
            """,
                source=source,
                last_value=last_value,
                last_id=last_id,
                rows_processed=total_rows,
            )
            
            logger.info(
                f"Watermark saved for {source}: "
                f"last_value={last_value}, rows_processed={total_rows}"
            )
    
    def delete_watermark(self, source: str) -> None:
        """
        Delete watermark for a source (forces full reload on next run).
        
        Args:
            source: Source identifier
        """
        with self.driver.session() as session:
            session.run("""
                MATCH (w:Watermark {source: $source})
                DELETE w
            """, source=source)
            
            logger.info(f"Watermark deleted for {source}")
    
    def list_watermarks(self) -> list[dict[str, Any]]:
        """
        List all watermarks.
        
        Returns:
            List of watermark dicts with source and metadata
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (w:Watermark)
                RETURN w.source AS source,
                       w.last_value AS last_value,
                       w.last_id AS last_id,
                       w.updated_at AS updated_at,
                       w.rows_processed AS rows_processed
                ORDER BY w.source
            """)
            
            return [
                {
                    "source": record["source"],
                    "last_value": record["last_value"],
                    "last_id": record["last_id"],
                    "updated_at": record["updated_at"],
                    "rows_processed": record["rows_processed"] or 0,
                }
                for record in result
            ]
    
    def get_watermark_timestamp(self, source: str) -> datetime | None:
        """
        Get watermark as datetime for time-based incremental loading.
        
        Args:
            source: Source identifier
            
        Returns:
            datetime of last load, or None if no watermark exists
        """
        wm = self.get_watermark(source)
        last_value = wm.get("last_value")
        
        if last_value is None:
            return None
        
        # Try to parse as datetime
        if isinstance(last_value, datetime):
            return last_value
        
        # Try string parsing
        for fmt in [
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]:
            try:
                return datetime.fromisoformat(last_value)
            except (ValueError, TypeError):
                continue
        
        logger.warning(f"Could not parse watermark timestamp: {last_value}")
        return None


# Convenience function for use in ETL scripts
def get_incremental_data(
    source: str,
    fetch_function: callable,
    load_function: callable,
    driver: Neo4jConnection | None = None,
) -> dict[str, int]:
    """
    Helper function for incremental ETL pattern.
    
    Usage:
        def fetch(since):
            return api.get_tenders(since=since)
        
        def load(data):
            neo4j.load(data)
        
        result = get_incremental_data("anac_tenders", fetch, load)
        # result = {"rows_fetched": 100, "rows_loaded": 100}
    
    Args:
        source: Source identifier for watermark
        fetch_function: Function to fetch data, receives 'since' parameter
        load_function: Function to load data to Neo4j
        driver: Neo4j connection
        
    Returns:
        Dict with rows_fetched and rows_loaded counts
    """
    wm = WatermarkManager(driver)
    
    # Get last watermark
    since = wm.get_watermark_timestamp(source)
    
    # Fetch new data
    logger.info(f"Fetching data from {source} since {since}")
    new_data = fetch_function(since=since)
    
    if not new_data:
        logger.info(f"No new data for {source}")
        return {"rows_fetched": 0, "rows_loaded": 0}
    
    # Load data
    load_function(new_data)
    
    # Update watermark (assume last item has max timestamp)
    if new_data and hasattr(new_data[0], "get"):
        last_value = new_data[-1].get("updated_at") or new_data[-1].get("date")
        wm.save_watermark(
            source=source,
            last_value=last_value,
            incremental_rows=len(new_data),
        )
    
    return {
        "rows_fetched": len(new_data),
        "rows_loaded": len(new_data),
    }
