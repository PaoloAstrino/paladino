"""
Incremental sync tracker for corporate-structure data.

Stores a ``last_sync`` timestamp in the Neo4j graph (as a ``Synccheckpoint``
node) so that subsequent ETL runs only process records that are *newer* than
the previous run.

This module is intentionally simple: it does **not** implement a
change-data-capture feed (that would require paid Infocamere/ATOKA webhooks).
Instead it:
  1. Records the wall-clock time of every successful ETL run.
  2. Filters CSVs to only re-process rows whose ``data_rilevazione`` /
     ``data_inizio`` column is newer than the last checkpoint.
  3. Lets callers skip the full reload when nothing has changed.

Usage
──────────────────────────────────────────────────────────────────────────────
    from paladino.etl.corporate.incremental_sync import CorporateSyncTracker
    from paladino.db import Neo4jConnection

    conn    = Neo4jConnection()
    tracker = CorporateSyncTracker(conn)

    last = tracker.get_last_sync()          # datetime | None
    # … run ETL, filter rows newer than `last` …
    tracker.record_sync(rows_written=2500)  # save the new checkpoint
    conn.close()
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from paladino.db import Neo4jConnection


_CHECKPOINT_LABEL = "SyncCheckpoint"
_CORPORATE_KEY    = "corporate_etl"


class CorporateSyncTracker:
    """
    Persist and query incremental-sync checkpoints for corporate ETL runs.

    Parameters
    ----------
    conn:
        Active :class:`~paladino.db.Neo4jConnection`.
    """

    def __init__(self, conn: Neo4jConnection) -> None:
        self.conn = conn

    # ── public API ───────────────────────────────────────────────────────────

    def get_last_sync(self) -> Optional[datetime]:
        """
        Return the timestamp of the most recent successful corporate ETL run,
        or ``None`` if this is the first run.
        """
        rows = self.conn.run_query(
            f"""
            MATCH (c:{_CHECKPOINT_LABEL} {{key: $key}})
            RETURN c.last_sync_utc AS ts
            ORDER BY c.last_sync_utc DESC
            LIMIT 1
            """,
            {"key": _CORPORATE_KEY},
        )
        if not rows or rows[0]["ts"] is None:
            return None

        ts_raw = rows[0]["ts"]
        # Neo4j may return as string or datetime; normalise to datetime
        if isinstance(ts_raw, str):
            try:
                return datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                logger.warning(f"[sync] Could not parse last_sync_utc: {ts_raw!r}")
                return None
        if isinstance(ts_raw, datetime):
            if ts_raw.tzinfo is None:
                return ts_raw.replace(tzinfo=timezone.utc)
            return ts_raw
        return None

    def record_sync(
        self,
        rows_written:  int = 0,
        persons:       int = 0,
        represents:    int = 0,
        shareholdings: int = 0,
    ) -> None:
        """
        Upsert a ``SyncCheckpoint`` node with the current UTC timestamp and
        counts from this ETL run.

        This is idempotent — safe to call after a partial run.
        """
        now = datetime.now(timezone.utc).isoformat()
        self.conn.run_query(
            f"""
            MERGE (c:{_CHECKPOINT_LABEL} {{key: $key}})
            SET c.last_sync_utc   = $now,
                c.rows_written    = $rows_written,
                c.persons         = $persons,
                c.represents      = $represents,
                c.shareholdings   = $shareholdings,
                c.updated_at      = $now
            """,
            {
                "key":          _CORPORATE_KEY,
                "now":          now,
                "rows_written": rows_written,
                "persons":      persons,
                "represents":   represents,
                "shareholdings": shareholdings,
            },
        )
        logger.info(
            f"[sync] Checkpoint saved — last_sync={now}  "
            f"rows={rows_written:,}  persons={persons:,}  "
            f"represents={represents:,}  shareholdings={shareholdings:,}"
        )

    def get_history(self, limit: int = 10) -> list[dict]:
        """
        Return the *limit* most recent sync checkpoints.

        Each dict has: key, last_sync_utc, rows_written, persons,
        represents, shareholdings.
        """
        return self.conn.run_query(
            f"""
            MATCH (c:{_CHECKPOINT_LABEL} {{key: $key}})
            RETURN c.last_sync_utc   AS last_sync_utc,
                   c.rows_written    AS rows_written,
                   c.persons         AS persons,
                   c.represents      AS represents,
                   c.shareholdings   AS shareholdings
            ORDER BY c.last_sync_utc DESC
            LIMIT $limit
            """,
            {"key": _CORPORATE_KEY, "limit": limit},
        )

    def should_skip(self, max_age_hours: float = 24.0) -> bool:
        """
        Return True when the last successful sync was *less than*
        ``max_age_hours`` ago — indicating a fresh-enough dataset.

        Useful for scheduling: skip the ETL if run recently.
        """
        last = self.get_last_sync()
        if last is None:
            return False
        age = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        if age < max_age_hours:
            logger.info(
                f"[sync] Skipping corporate ETL — last run {age:.1f}h ago "
                f"(threshold {max_age_hours}h)"
            )
            return True
        return False
