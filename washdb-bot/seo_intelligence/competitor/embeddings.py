"""
Vector embeddings generation and Qdrant integration.

Generates semantic embeddings of competitor content for:
- Similar content discovery
- Topic clustering
- Content gap analysis
"""
import logging
import os
import uuid
from typing import Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class EmbeddingsGenerator:
    """
    Generates and stores vector embeddings for competitor pages.

    Features:
    - Sentence-transformers embeddings (384-dimensional)
    - Qdrant vector database integration
    - Automatic collection creation
    - Metadata storage (URL, title, domain, timestamp)
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        qdrant_url: Optional[str] = None,
        qdrant_api_key: Optional[str] = None,
        collection_name: str = "competitor_pages"
    ):
        """
        Initialize embeddings generator.

        Args:
            model_name: Sentence-transformers model (default: all-MiniLM-L6-v2)
            qdrant_url: Qdrant server URL (defaults to QDRANT_URL env var)
            qdrant_api_key: Qdrant API key (optional)
            collection_name: Qdrant collection name (default: competitor_pages)
        """
        self.model_name = model_name
        self.collection_name = collection_name

        # Load embedding model
        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        logger.info(f"Model loaded: {self.embedding_dim}-dimensional embeddings")

        # Connect to Qdrant
        self.qdrant_url = qdrant_url or os.getenv("QDRANT_URL", "http://localhost:6333")
        self.qdrant_api_key = qdrant_api_key or os.getenv("QDRANT_API_KEY")

        logger.info(f"Connecting to Qdrant: {self.qdrant_url}")
        self.client = QdrantClient(
            url=self.qdrant_url,
            api_key=self.qdrant_api_key
        )

        # Ensure collection exists
        self._ensure_collection()

    def _ensure_collection(self):
        """Create Qdrant collection if it doesn't exist."""
        try:
            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]

            if self.collection_name not in collection_names:
                logger.info(f"Creating Qdrant collection: {self.collection_name}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.embedding_dim,
                        distance=Distance.COSINE
                    )
                )
                logger.info(f"Collection created: {self.collection_name}")
            else:
                logger.debug(f"Collection already exists: {self.collection_name}")

        except Exception as e:
            logger.error(f"Error ensuring collection: {e}")
            raise

    def _extract_text(self, parsed_data: Dict) -> str:
        """
        Extract text content from parsed page data.

        Args:
            parsed_data: Parsed data from PageParser

        Returns:
            Combined text content
        """
        text_parts = []

        # Add title
        if parsed_data.get('meta', {}).get('title'):
            text_parts.append(parsed_data['meta']['title'])

        # Add description
        if parsed_data.get('meta', {}).get('description'):
            text_parts.append(parsed_data['meta']['description'])

        # Add H1/H2 headers
        headers = parsed_data.get('headers', {})
        for h1 in headers.get('h1', []):
            text_parts.append(h1)
        for h2 in headers.get('h2', [])[:5]:  # Limit H2s
            text_parts.append(h2)

        # Add schema descriptions
        for schema in parsed_data.get('schema', []):
            if isinstance(schema, dict) and 'description' in schema:
                text_parts.append(schema['description'])

        # Combine with separator
        text = ' | '.join(text_parts)

        return text

    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding vector for text.

        Args:
            text: Input text

        Returns:
            Embedding vector
        """
        try:
            embedding = self.model.encode(text, convert_to_numpy=True)
            return embedding.tolist()

        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise

    def upsert_page(
        self,
        page_id: int,
        url: str,
        parsed_data: Dict,
        additional_metadata: Optional[Dict] = None
    ) -> str:
        """
        Generate embedding and upsert to Qdrant.

        Args:
            page_id: CompetitorPage database ID
            url: Page URL
            parsed_data: Parsed data from PageParser
            additional_metadata: Additional metadata to store (optional)

        Returns:
            Qdrant point ID
        """
        try:
            # Extract text
            text = self._extract_text(parsed_data)

            if not text:
                logger.warning(f"No text content for {url}, skipping embedding")
                return None

            # Generate embedding
            logger.debug(f"Generating embedding for {url}")
            embedding = self.generate_embedding(text)

            # Build metadata
            from urllib.parse import urlparse

            parsed_url = urlparse(url)
            metadata = {
                'page_id': page_id,
                'url': url,
                'domain': parsed_url.netloc,
                'title': parsed_data.get('meta', {}).get('title', ''),
                'text_preview': text[:200]
            }

            # Add additional metadata
            if additional_metadata:
                metadata.update(additional_metadata)

            # Generate point ID (use page_id as UUID namespace)
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, url))

            # Upsert to Qdrant
            point = PointStruct(
                id=point_id,
                vector=embedding,
                payload=metadata
            )

            self.client.upsert(
                collection_name=self.collection_name,
                points=[point]
            )

            logger.info(f"Upserted embedding for {url} (point_id: {point_id})")
            return point_id

        except Exception as e:
            logger.error(f"Error upserting page {url}: {e}")
            raise

    def search_similar(
        self,
        query_text: str,
        limit: int = 10,
        score_threshold: Optional[float] = None
    ) -> List[Dict]:
        """
        Search for similar pages by text query.

        Args:
            query_text: Search query
            limit: Maximum results to return (default: 10)
            score_threshold: Minimum similarity score (optional)

        Returns:
            List of similar pages with scores
        """
        try:
            # Generate query embedding
            query_embedding = self.generate_embedding(query_text)

            # Search Qdrant
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=limit,
                score_threshold=score_threshold
            )

            # Format results
            similar_pages = []
            for result in results:
                similar_pages.append({
                    'point_id': result.id,
                    'score': result.score,
                    'page_id': result.payload.get('page_id'),
                    'url': result.payload.get('url'),
                    'title': result.payload.get('title'),
                    'domain': result.payload.get('domain')
                })

            logger.info(f"Found {len(similar_pages)} similar pages for query")
            return similar_pages

        except Exception as e:
            logger.error(f"Error searching similar pages: {e}")
            return []

    def delete_page(self, url: str):
        """
        Delete page embedding from Qdrant.

        Args:
            url: Page URL
        """
        try:
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, url))

            self.client.delete(
                collection_name=self.collection_name,
                points_selector=[point_id]
            )

            logger.info(f"Deleted embedding for {url}")

        except Exception as e:
            logger.error(f"Error deleting embedding for {url}: {e}")
            raise


# Global embeddings generator (lazy initialization)
_embeddings_generator = None


def get_embeddings_generator() -> EmbeddingsGenerator:
    """Get or create global embeddings generator instance."""
    global _embeddings_generator

    if _embeddings_generator is None:
        _embeddings_generator = EmbeddingsGenerator()

    return _embeddings_generator


# Convenience functions
def generate_embedding(text: str) -> List[float]:
    """Generate embedding vector for text."""
    generator = get_embeddings_generator()
    return generator.generate_embedding(text)


def upsert_page(
    page_id: int,
    url: str,
    parsed_data: Dict,
    additional_metadata: Optional[Dict] = None
) -> str:
    """Generate embedding and upsert to Qdrant."""
    generator = get_embeddings_generator()
    return generator.upsert_page(page_id, url, parsed_data, additional_metadata)


def search_similar(
    query_text: str,
    limit: int = 10,
    score_threshold: Optional[float] = None
) -> List[Dict]:
    """Search for similar pages by text query."""
    generator = get_embeddings_generator()
    return generator.search_similar(query_text, limit, score_threshold)


def delete_page(url: str):
    """Delete page embedding from Qdrant."""
    generator = get_embeddings_generator()
    generator.delete_page(url)
