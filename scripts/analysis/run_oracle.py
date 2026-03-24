#!/usr/bin/env python
"""
Entry point for the Paladino Oracle.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paladino.db import Neo4jConnection
from paladino.analytics.oracle import Oracle

def main():
    try:
        conn = Neo4jConnection()
        oracle = Oracle(conn)
        oracle.run_investigative_summary()
    except Exception as e:
        print(f"Error starting Oracle: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    main()
