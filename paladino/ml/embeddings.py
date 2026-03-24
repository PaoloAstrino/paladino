"""
Embedding generation for semantic search.
"""

from loguru import logger
from sentence_transformers import SentenceTransformer


class EmbeddingManager:
    """Manages generation of vector embeddings."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize embedding manager.

        Raises:
            RuntimeError: If the embedding model fails to load
        """
        logger.info(f"Loading embedding model: {model_name}...")
        try:
            self.model = SentenceTransformer(model_name)
            logger.success("Embedding model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise RuntimeError(
                f"Embedding model '{model_name}' required but failed to load: {e}"
            ) from e

    def generate(self, text: str | list[str]) -> list[list[float]]:
        """
        Generate embeddings for the given text or list of texts.

        Args:
            text: Single string or list of strings to embed

        Returns:
            List of embedding vectors (list of floats)

        Raises:
            ValueError: If text is empty or contains only whitespace
            RuntimeError: If embedding model is not initialized
        """
        if not self.model:
            logger.error("Embedding model not initialized")
            raise RuntimeError("Embedding model not initialized")

        # Validate input
        if isinstance(text, str):
            if not text.strip():
                raise ValueError("Input text cannot be empty or whitespace-only")
            text = [text]
        elif isinstance(text, list):
            if not text:
                raise ValueError("Input text list cannot be empty")
            for i, t in enumerate(text):
                if not isinstance(t, str) or not t.strip():
                    raise ValueError(f"Text at index {i} is empty or not a string")
        else:
            raise TypeError(f"Expected str or list of str, got {type(text).__name__}")

        logger.debug(f"Generating embeddings for {len(text)} items...")
        embeddings = self.model.encode(text)

        # Convert to list of lists (standard format for Neo4j)
        return embeddings.tolist()

    def generate_single(self, text: str) -> list[float]:
        """
        Generate embedding for a single text string.

        Args:
            text: Single string to embed

        Returns:
            Embedding vector as list of floats

        Raises:
            ValueError: If text is empty or whitespace-only
        """
        embeddings = self.generate(text)
        return embeddings[0] if embeddings else []
