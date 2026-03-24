#!/usr/bin/env python3
"""
Initialize Neo4j schema (constraints and indexes).
"""

from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paladino.db import get_driver
from paladino.schema_manager import SchemaManager
from loguru import logger


def main():
    """Initialize the Neo4j schema."""
    logger.info("Starting schema initialization...")
    
    # Get schema directory
    schema_dir = Path(__file__).parent.parent / "schema"
    
    if not schema_dir.exists():
        logger.error(f"Schema directory not found: {schema_dir}")
        sys.exit(1)
    
    # Connect to Neo4j
    driver = get_driver()
    
    try:
        # Verify connectivity
        driver.verify_connectivity()
        logger.success("Connected to Neo4j")
        
        # Initialize schema
        manager = SchemaManager(driver, schema_dir)
        manager.initialize_schema()
        
        # Validate
        if manager.validate_schema():
            logger.success("✓ Schema initialization successful")
        else:
            logger.error("✗ Schema validation failed")
            sys.exit(1)
    
    except Exception as e:
        logger.error(f"Schema initialization failed: {e}")
        sys.exit(1)
    
    finally:
        driver.close()


if __name__ == "__main__":
    main()
