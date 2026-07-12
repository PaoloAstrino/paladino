#!/usr/bin/env python
"""
Entry point for the Paladino Oracle.
"""

import sys
from pathlib import Path
import argparse

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from paladino.analytics.oracle import Oracle
from paladino.analytics.temporal_oracle import TemporalOracle
from paladino.db import Neo4jConnection


def main():
    parser = argparse.ArgumentParser(description="Paladino Oracle - Proactive Network Intelligence")
    parser.add_argument("--temporal", action="store_true", help="Run temporal drift analysis")
    args = parser.parse_args()

    try:
        conn = Neo4jConnection()
        
        # 1. Standard Oracle (Snapshot Analysis)
        oracle = Oracle(conn)
        oracle.run_investigative_summary()
        
        # 2. Temporal Oracle (Drift Analysis)
        if args.temporal:
            temporal = TemporalOracle(conn)
            temporal.run_full_scan()
            
    except Exception as e:
        print(f"Error starting Oracle: {e}")
    finally:
        if "conn" in locals():
            conn.close()


if __name__ == "__main__":
    main()
