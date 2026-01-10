"""
Qdrant Vector Database Manager

Manages connections and operations for the Qdrant vector database used for
semantic search of competitor pages and SERP snippets.

Per SCRAPER BOT.pdf specification:
- Store embeddings for competitor pages and SERP snippets
- Payload structure: {page_id, site_id, url, title, page_type}
- Support quarterly re-embedding on model changes
"""

import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue
)


@dataclass
class EmbeddingPoint:
    """Represents a point to be inserted into Qdrant"""
    id: str  # Deterministic ID (e.g., f"page_{page_id}")
    vector: List[float]
    payload: Dict[str, Any]


class QdrantManager:
    """
    Manages Qdrant vector database operations.

    Collections:
    - competitor_pages: Embeddings of competitor content
    - serp_snippets: Embeddings of SERP result snippets
    """

    def __init__(self):
        """Initialize Qdrant client from environment variables"""
        self.host = os.getenv("QDRANT_HOST", "127.0.0.1")
        self.port = int(os.getenv("QDRANT_PORT", 6333))
        self.api_key = os.getenv("QDRANT_API_KEY")
        self.https = os.getenv("QDRANT_HTTPS", "false").lower() == "true"
        self.dimension = int(os.getenv("EMBEDDING_DIMENSION", 384))

        # Initialize client
        self.client = QdrantClient(
            host=self.host,
            port=self.port,
            api_key=self.api_key if self.api_key else None,
            https=self.https
        )

        # Collection names
        self.COMPETITOR_PAGES = "competitor_pages"
        self.SERP_SNIPPETS = "serp_snippets"

    def initialize_collections(self):
        """
        Create Qdrant collections if they don't exist.

        Per spec: Collections for competitor pages and SERP snippets
        with appropriate vector dimensions.
        """
        collections = [self.COMPETITOR_PAGES, self.SERP_SNIPPETS]

        for collection_name in collections:
            if not self.client.collection_exists(collection_name):
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=self.dimension,
                        distance=Distance.COSINE
                    )
                )
                print(f"✓ Created Qdrant collection: {collection_name}")
            else:
                print(f"✓ Collection already exists: {collection_name}")

    def upsert_competitor_page(
        self,
        page_id: int,
        site_id: int,
        url: str,
        title: str,
        page_type: str,
        vector: List[float]
    ) -> str:
        """
        Upsert a competitor page embedding to Qdrant.

        Args:
            page_id: Database page ID
            site_id: Competitor site ID
            url: Page URL
            title: Page title
            page_type: Type classification (homepage, service, blog, etc.)
            vector: Embedding vector

        Returns:
            Point ID (integer)
        """
        # Use integer ID directly - Qdrant requires int or UUID, not strings
        payload = {
            "page_id": page_id,
            "site_id": site_id,
            "url": url,
            "title": title,
            "page_type": page_type,
            "embedding_version": os.getenv("EMBEDDING_VERSION", "v1.0")
        }

        point = PointStruct(
            id=page_id,  # Use integer directly
            vector=vector,
            payload=payload
        )

        self.client.upsert(
            collection_name=self.COMPETITOR_PAGES,
            points=[point]
        )

        return page_id

    def upsert_serp_snippet(
        self,
        result_id: int,
        query: str,
        url: str,
        title: str,
        snippet: str,
        rank: int,
        vector: List[float]
    ) -> str:
        """
        Upsert a SERP snippet embedding to Qdrant.

        Args:
            result_id: SERP result ID
            query: Search query
            url: Result URL
            title: Result title
            snippet: Result snippet text
            rank: Search result rank
            vector: Embedding vector

        Returns:
            Point ID (integer)
        """
        # Use integer ID directly - Qdrant requires int or UUID, not strings
        payload = {
            "result_id": result_id,
            "query": query,
            "url": url,
            "title": title,
            "snippet": snippet,
            "rank": rank,
            "embedding_version": os.getenv("EMBEDDING_VERSION", "v1.0")
        }

        point = PointStruct(
            id=result_id,  # Use integer directly
            vector=vector,
            payload=payload
        )

        self.client.upsert(
            collection_name=self.SERP_SNIPPETS,
            points=[point]
        )

        return result_id

    def search_similar_pages(
        self,
        query_vector: List[float],
        limit: int = 10,
        page_type: Optional[str] = None,
        site_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar competitor pages.

        Args:
            query_vector: Query embedding vector
            limit: Maximum number of results
            page_type: Optional filter by page type
            site_id: Optional filter by site ID

        Returns:
            List of search results with scores and payloads
        """
        query_filter = None

        # Build filter if needed
        if page_type or site_id:
            must_conditions = []
            if page_type:
                must_conditions.append(
                    FieldCondition(
                        key="page_type",
                        match=MatchValue(value=page_type)
                    )
                )
            if site_id:
                must_conditions.append(
                    FieldCondition(
                        key="site_id",
                        match=MatchValue(value=site_id)
                    )
                )
            query_filter = Filter(must=must_conditions)

        results = self.client.search(
            collection_name=self.COMPETITOR_PAGES,
            query_vector=query_vector,
            limit=limit,
            query_filter=query_filter
        )

        return [
            {
                "score": result.score,
                "page_id": result.payload["page_id"],
                "url": result.payload["url"],
                "title": result.payload["title"],
                "page_type": result.payload["page_type"],
                "site_id": result.payload["site_id"]
            }
            for result in results
        ]

    def search_similar_snippets(
        self,
        query_vector: List[float],
        limit: int = 10,
        query_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar SERP snippets.

        Args:
            query_vector: Query embedding vector
            limit: Maximum number of results
            query_filter: Optional filter by search query

        Returns:
            List of search results with scores and payloads
        """
        filter_obj = None
        if query_filter:
            filter_obj = Filter(
                must=[
                    FieldCondition(
                        key="query",
                        match=MatchValue(value=query_filter)
                    )
                ]
            )

        results = self.client.search(
            collection_name=self.SERP_SNIPPETS,
            query_vector=query_vector,
            limit=limit,
            query_filter=filter_obj
        )

        return [
            {
                "score": result.score,
                "result_id": result.payload["result_id"],
                "query": result.payload["query"],
                "url": result.payload["url"],
                "title": result.payload["title"],
                "snippet": result.payload["snippet"],
                "rank": result.payload["rank"]
            }
            for result in results
        ]

    def delete_by_page_id(self, page_id: int):
        """Delete embedding for a specific page"""
        self.client.delete(
            collection_name=self.COMPETITOR_PAGES,
            points_selector=[page_id]  # Use integer directly
        )

    def delete_by_site_id(self, site_id: int):
        """Delete all embeddings for a specific site"""
        self.client.delete(
            collection_name=self.COMPETITOR_PAGES,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="site_id",
                        match=MatchValue(value=site_id)
                    )
                ]
            )
        )

    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        """Get statistics for a collection"""
        info = self.client.get_collection(collection_name)
        # Handle different qdrant_client versions
        return {
            "vectors_count": getattr(info, 'vectors_count', None) or info.points_count,
            "indexed_vectors_count": getattr(info, 'indexed_vectors_count', 0),
            "points_count": info.points_count,
            "status": str(info.status)
        }

    def health_check(self) -> bool:
        """Check if Qdrant is accessible"""
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False


# Singleton instance
_qdrant_manager = None


def get_qdrant_manager() -> QdrantManager:
    """Get or create singleton Qdrant manager instance"""
    global _qdrant_manager
    if _qdrant_manager is None:
        _qdrant_manager = QdrantManager()
    return _qdrant_manager
