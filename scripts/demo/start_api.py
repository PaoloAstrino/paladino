#!/usr/bin/env python3
"""
Start the Paladino FastAPI server.
"""

import uvicorn
from loguru import logger


def main():
    """Start the API server."""
    logger.info("Starting Paladino GraphRAG API server...")
    logger.info("API documentation: http://localhost:8000/docs")

    uvicorn.run("paladino.app.api:app", host="0.0.0.0", port=8000, reload=True, log_level="info")


if __name__ == "__main__":
    main()
