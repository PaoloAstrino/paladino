"""
Neo4j database connection and utilities.
"""

import logging
from typing import Any

from loguru import logger
from neo4j import Driver, GraphDatabase
from neo4j.exceptions import AuthError, DatabaseUnavailable, DriverError, ServiceUnavailable
from pydantic_settings import BaseSettings

from paladino.config import settings
from paladino.errors import (
    DatabaseError,
    neo4j_auth_error,
    neo4j_offline_error,
    neo4j_timeout_error,
)

# Suppress "Received notification from DBMS server" spam (property doesn't exist, etc.)
# These are advisory WARN-level messages from the Neo4j driver's notification system.
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)


class Neo4jSettings(BaseSettings):
    """Neo4j connection settings."""

    uri: str = settings.neo4j_uri
    user: str = settings.neo4j_user
    password: str = settings.neo4j_password
    database: str = settings.neo4j_database

    class Config:
        env_prefix = "NEO4J_"
        env_file = ".env"


class Neo4jConnection:
    """Neo4j database connection manager."""

    def __init__(self, settings: Neo4jSettings | None = None):
        self.settings = settings or Neo4jSettings()
        self._driver: Driver | None = None

    def connect(self) -> Driver:
        """Establish connection to Neo4j.

        Raises:
            DatabaseAuthError: If credentials are wrong.
            DatabaseError: If Neo4j is unreachable.
        """
        if self._driver is None:
            try:
                self._driver = GraphDatabase.driver(
                    self.settings.uri,
                    auth=(self.settings.user, self.settings.password),
                    connection_timeout=10,
                    # Suppress property-doesn't-exist and similar advisory
                    # notifications that would otherwise spam the terminal.
                    notifications_min_severity="OFF",
                )
            except AuthError as e:
                raise neo4j_auth_error(e) from e
            except (ServiceUnavailable, DatabaseUnavailable, DriverError) as e:
                raise neo4j_offline_error(e) from e
        return self._driver

    def close(self):
        """Close the connection."""
        if self._driver:
            self._driver.close()
            self._driver = None

    def verify_connectivity(self) -> bool:
        """Test database connectivity.

        Returns True on success.  Does NOT swallow errors silently — the caller
        can inspect the raised exception for a user-friendly message.

        Raises:
            DatabaseAuthError: wrong credentials.
            DatabaseError: cannot reach Neo4j.
        """
        try:
            driver = self.connect()
            driver.verify_connectivity()
            return True
        except (DatabaseError,):
            raise
        except AuthError as e:
            raise neo4j_auth_error(e) from e
        except (ServiceUnavailable, DatabaseUnavailable, DriverError) as e:
            raise neo4j_offline_error(e) from e
        except Exception as e:
            # SECURITY FIX (SEC-013): Don't leak connection details in error message
            logger.error("Neo4j connectivity check failed")
            raise DatabaseError(
                message="Neo4j connectivity check failed",
                hint="Check that your NEO4J_URI is correct and Neo4j is running.",
            ) from e

    def execute_batch(
        self,
        query: str,
        data: list[dict[str, Any]],
        batch_size: int = 5000,
        source_tag: str = "default",
    ) -> None:
        """Execute a Cypher query in batches with checkpointing.

        Failed batches are marked FAILED in the graph so they can be retried.
        """
        import hashlib

        driver = self.connect()
        total = len(data)

        for i in range(0, total, batch_size):
            batch = data[i : i + batch_size]
            # Generate a unique ID for this batch to check if it was already processed
            batch_content_hash = hashlib.md5(str(batch).encode()).hexdigest()
            batch_id = f"{source_tag}_{i}_{batch_content_hash}"

            # Atomically claim the batch (avoids race condition)
            if not self._claim_batch(batch_id, source_tag):
                logger.debug(
                    f"  Skipping batch {i // batch_size + 1} (already processed or claimed)."
                )
                continue

            try:
                with driver.session() as session:
                    session.run(query, batch=batch)
                self.mark_batch_completed(batch_id, len(batch))
                logger.debug(
                    f"  Processed batch {i // batch_size + 1} ({min(i + batch_size, total)}/{total})"
                )
            except AuthError as e:
                raise neo4j_auth_error(e) from e
            except (ServiceUnavailable, DatabaseUnavailable, DriverError) as e:
                logger.error(f"Neo4j unreachable during batch {batch_id}")
                self._mark_batch_failed(batch_id, "Neo4j service unavailable")
                raise neo4j_offline_error(e) from e
            except Exception as e:
                logger.error(f"Failed to process batch {batch_id}")
                self._mark_batch_failed(batch_id, str(e)[:100])  # Truncate error message
                raise DatabaseError(
                    message=f"Batch {batch_id} failed",
                    hint="Check the Cypher query and data format.",
                ) from e

    def is_batch_processed(self, batch_id: str) -> bool:
        """Check if a batch was successfully completed."""
        query = "MATCH (b:IngestionBatch {id: $id, status: 'COMPLETED'}) RETURN b"
        result = self.run_query(query, {"id": batch_id})
        return len(result) > 0

    def mark_batch_started(self, batch_id: str, source: str):
        """Log the start of a batch."""
        query = """
        MERGE (b:IngestionBatch {id: $id})
        SET b.source = $source,
            b.status = 'STARTED',
            b.started_at = datetime()
        """
        self.run_query(query, {"id": batch_id, "source": source})

    def mark_batch_completed(self, batch_id: str, count: int):
        """Mark a batch as successfully completed."""
        query = """
        MATCH (b:IngestionBatch {id: $id})
        SET b.status = 'COMPLETED',
            b.completed_at = datetime(),
            b.records_count = $count
        """
        self.run_query(query, {"id": batch_id, "count": count})

    def _mark_batch_failed(self, batch_id: str, error_msg: str):
        """Mark a batch as FAILED so it can be retried later."""
        try:
            query = """
            MERGE (b:IngestionBatch {id: $id})
            SET b.status = 'FAILED',
                b.failed_at = datetime(),
                b.error = $error
            """
            self.run_query(query, {"id": batch_id, "error": error_msg[:500]})
        except Exception:
            pass  # Best-effort; don't mask the original error.

    def _claim_batch(self, batch_id: str, source: str) -> bool:
        """
        Atomically claim a batch for processing.

        Returns True if this process successfully claimed the batch,
        False if the batch was already completed or claimed by another process.
        """
        query = """
        MERGE (b:IngestionBatch {id: $id})
        ON CREATE SET b.source = $source,
                      b.status = 'PROCESSING',
                      b.started_at = datetime()
        ON MATCH SET b.status = CASE
            WHEN b.status = 'COMPLETED' THEN 'COMPLETED'
            WHEN b.status = 'PROCESSING' THEN 'PROCESSING'
            ELSE 'PROCESSING'
        END
        WITH b
        WHERE b.status IN ['PROCESSING', 'COMPLETED'] AND b.started_at IS NOT NULL
        RETURN b.status as status
        """
        result = self.run_query(query, {"id": batch_id, "source": source})
        if not result:
            # Batch was created (ON CREATE), we claimed it
            return True
        # Batch already existed - check if it's completed
        status = result[0].get("status")
        return status != "COMPLETED"

    def run_query(
        self, query: str, parameters: dict[str, Any] | None = None, timeout: float | None = None
    ):
        """Execute a single Cypher query and return results.

        Args:
            query: Cypher query string.
            parameters: Optional query parameters.
            timeout: Override session-level timeout in seconds (default: no limit).

        Raises:
            DatabaseAuthError: Wrong credentials.
            DatabaseTimeoutError: Query timed out.
            DatabaseError: Other Neo4j errors.
        """
        import neo4j.exceptions as _nx

        driver = self.connect()
        try:
            with driver.session() as session:
                result = session.run(query, parameters, timeout=timeout)
                return list(result)
        except AuthError as e:
            raise neo4j_auth_error(e) from e
        except (ServiceUnavailable, DatabaseUnavailable, DriverError) as e:
            raise neo4j_offline_error(e) from e
        except _nx.ClientError as e:
            # e.g. syntax error – re-raise as DatabaseError with helpful hint
            raise DatabaseError(
                message="Cypher client error",
                hint="Review the query syntax and property names.",
            ) from e
        except Exception as e:
            # Check for timeout signal from Neo4j
            error_str = str(e).lower()
            if "timeout" in error_str:
                raise neo4j_timeout_error(query=query, original=e) from e
            # SECURITY FIX (SEC-013): Don't leak query details in error
            logger.error("Query execution failed")
            raise DatabaseError(
                message="Query execution failed", hint="Check query syntax and parameters"
            ) from e

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def get_driver() -> Driver:
    """Get a Neo4j driver instance."""
    conn = Neo4jConnection()
    return conn.connect()


def execute_batch(query: str, data: list, batch_size: int = 5000):
    """Global helper for batch execution."""
    conn = Neo4jConnection()
    conn.execute_batch(query, data, batch_size)
