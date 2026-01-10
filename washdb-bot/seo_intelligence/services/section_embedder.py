"""
Section-Level Embedding Service

Extends the existing embedding infrastructure to support section-level embeddings
for competitor pages. Stores each content section (split by H2/H3) as a separate
vector in Qdrant with rich metadata.

Benefits:
- Fine-grained semantic search (search within specific sections)
- Better content gap analysis
- FAQ generation from similar sections across competitors
- Section-level snippet drafting

Usage:
    from seo_intelligence.services.section_embedder import get_section_embedder

    embedder = get_section_embedder()

    # Embed page sections
    sections = [
        {'heading': 'Our Services', 'content': '...', 'word_count': 250},
        {'heading': 'Why Choose Us', 'content': '...', 'word_count': 180}
    ]

    embedder.embed_and_store_sections(
        page_id=123,
        site_id=45,
        url='https://example.com/services',
        page_type='services',
        sections=sections
    )
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
    MatchValue,
    Range
)

from seo_intelligence.services.embedding_service import get_content_embedder
from runner.logging_setup import get_logger

logger = get_logger("section_embedder")


@dataclass
class SectionEmbedding:
    """Represents a section-level embedding"""
    section_id: str  # Format: "page_{page_id}_section_{index}"
    page_id: int
    site_id: int
    url: str
    page_type: str
    section_index: int
    heading: str
    heading_level: str
    content: str
    word_count: int
    vector: List[float]


class SectionEmbedder:
    """
    Manages section-level embeddings for competitor pages.

    Extends the existing Qdrant infrastructure with a new collection for
    content sections, enabling fine-grained semantic search.
    """

    def __init__(self):
        """Initialize section embedder"""
        # Initialize Qdrant client
        self.host = os.getenv("QDRANT_HOST", "127.0.0.1")
        self.port = int(os.getenv("QDRANT_PORT", 6333))
        self.api_key = os.getenv("QDRANT_API_KEY")
        self.https = os.getenv("QDRANT_HTTPS", "false").lower() == "true"
        self.dimension = int(os.getenv("EMBEDDING_DIMENSION", 384))

        self.client = QdrantClient(
            host=self.host,
            port=self.port,
            api_key=self.api_key if self.api_key else None,
            https=self.https
        )

        # Collection name
        self.CONTENT_SECTIONS = "content_sections"

        # Get embedding service
        self.content_embedder = get_content_embedder()

        logger.info("SectionEmbedder initialized")

    def initialize_collection(self):
        """
        Create the content_sections collection if it doesn't exist.

        Schema:
        - Vector: Section content embedding (384-dim cosine)
        - Payload: page_id, site_id, url, page_type, section_index, heading,
                   heading_level, content_preview, word_count, embedding_version
        """
        if not self.client.collection_exists(self.CONTENT_SECTIONS):
            self.client.create_collection(
                collection_name=self.CONTENT_SECTIONS,
                vectors_config=VectorParams(
                    size=self.dimension,
                    distance=Distance.COSINE
                )
            )
            logger.info(f"✓ Created Qdrant collection: {self.CONTENT_SECTIONS}")
        else:
            logger.info(f"✓ Collection already exists: {self.CONTENT_SECTIONS}")

    def embed_and_store_sections(
        self,
        page_id: int,
        site_id: int,
        url: str,
        page_type: str,
        sections: List[Dict[str, Any]]
    ) -> int:
        """
        Embed and store all sections for a page.

        Args:
            page_id: Database page ID
            site_id: Competitor site ID
            url: Page URL
            page_type: Page classification (homepage, services, blog, etc.)
            sections: List of section dicts with heading, content, word_count, heading_level

        Returns:
            Number of sections successfully stored
        """
        if not sections:
            logger.warning(f"No sections to embed for page {page_id}")
            return 0

        # Prepare section texts for batch embedding
        section_texts = [section['content'] for section in sections]

        # Generate embeddings for all sections in batch (more efficient)
        logger.debug(f"Generating embeddings for {len(section_texts)} sections (page {page_id})")
        embeddings = self.content_embedder.embedder.embed_batch(section_texts)

        # Build points for Qdrant
        points = []
        for i, (section, embedding) in enumerate(zip(sections, embeddings)):
            # Generate unique integer ID: page_id * 10000 + section_index
            # Supports up to 10000 sections per page
            section_id = page_id * 10000 + i

            payload = {
                "page_id": page_id,
                "site_id": site_id,
                "url": url,
                "page_type": page_type,
                "section_index": i,
                "heading": section.get('heading', ''),
                "heading_level": section.get('heading_level', 'h2'),
                "content_preview": section['content'][:500],  # Store first 500 chars for display
                "word_count": section.get('word_count', 0),
                "embedding_version": os.getenv("EMBEDDING_VERSION", "v1.0"),
                "embedding_model": self.content_embedder.embedder.model_name
            }

            point = PointStruct(
                id=section_id,
                vector=embedding,
                payload=payload
            )
            points.append(point)

        # Upsert to Qdrant
        self.client.upsert(
            collection_name=self.CONTENT_SECTIONS,
            points=points
        )

        logger.info(
            f"Stored {len(points)} section embeddings for page {page_id} ({url})"
        )

        return len(points)

    def search_similar_sections(
        self,
        query_text: str,
        limit: int = 10,
        page_type: Optional[str] = None,
        site_id: Optional[int] = None,
        min_word_count: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar content sections using semantic search.

        Args:
            query_text: Text to search for
            limit: Maximum number of results
            page_type: Optional filter by page type
            site_id: Optional filter by site ID
            min_word_count: Optional minimum word count filter

        Returns:
            List of search results with scores, headings, and content previews
        """
        # Generate query embedding
        query_vector = self.content_embedder.embed_single(query_text)

        # Build filter
        query_filter = None
        if page_type or site_id or min_word_count:
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
            if min_word_count:
                must_conditions.append(
                    FieldCondition(
                        key="word_count",
                        range=Range(gte=min_word_count)
                    )
                )
            query_filter = Filter(must=must_conditions)

        # Search Qdrant
        results = self.client.search(
            collection_name=self.CONTENT_SECTIONS,
            query_vector=query_vector,
            limit=limit,
            query_filter=query_filter
        )

        # Format results
        return [
            {
                "score": result.score,
                "page_id": result.payload["page_id"],
                "site_id": result.payload["site_id"],
                "url": result.payload["url"],
                "page_type": result.payload["page_type"],
                "section_index": result.payload["section_index"],
                "heading": result.payload["heading"],
                "heading_level": result.payload["heading_level"],
                "content_preview": result.payload["content_preview"],
                "word_count": result.payload["word_count"]
            }
            for result in results
        ]

    def search_sections_by_heading(
        self,
        heading_query: str,
        limit: int = 20,
        page_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Find sections with similar headings (useful for finding common patterns).

        Args:
            heading_query: Heading text to search for
            limit: Maximum number of results
            page_type: Optional filter by page type

        Returns:
            List of sections with similar headings
        """
        # Embed the heading query
        query_vector = self.content_embedder.embed_single(heading_query)

        # Build filter
        query_filter = None
        if page_type:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="page_type",
                        match=MatchValue(value=page_type)
                    )
                ]
            )

        # Search
        results = self.client.search(
            collection_name=self.CONTENT_SECTIONS,
            query_vector=query_vector,
            limit=limit,
            query_filter=query_filter
        )

        return [
            {
                "score": result.score,
                "heading": result.payload["heading"],
                "url": result.payload["url"],
                "page_type": result.payload["page_type"],
                "content_preview": result.payload["content_preview"]
            }
            for result in results
        ]

    def get_sections_for_page(self, page_id: int) -> List[Dict[str, Any]]:
        """
        Retrieve all sections for a specific page.

        Args:
            page_id: Database page ID

        Returns:
            List of sections ordered by section_index
        """
        # Scroll through all sections for this page
        results, _ = self.client.scroll(
            collection_name=self.CONTENT_SECTIONS,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="page_id",
                        match=MatchValue(value=page_id)
                    )
                ]
            ),
            limit=100  # Max sections per page
        )

        # Sort by section_index
        sections = [
            {
                "section_index": point.payload["section_index"],
                "heading": point.payload["heading"],
                "heading_level": point.payload["heading_level"],
                "content_preview": point.payload["content_preview"],
                "word_count": point.payload["word_count"]
            }
            for point in results
        ]

        sections.sort(key=lambda x: x["section_index"])
        return sections

    def delete_page_sections(self, page_id: int):
        """
        Delete all sections for a specific page.

        Args:
            page_id: Database page ID
        """
        # Get all section IDs for this page
        results, _ = self.client.scroll(
            collection_name=self.CONTENT_SECTIONS,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="page_id",
                        match=MatchValue(value=page_id)
                    )
                ]
            ),
            limit=100
        )

        point_ids = [point.id for point in results]

        if point_ids:
            self.client.delete(
                collection_name=self.CONTENT_SECTIONS,
                points_selector=point_ids
            )
            logger.info(f"Deleted {len(point_ids)} sections for page {page_id}")

    def delete_site_sections(self, site_id: int):
        """
        Delete all sections for a specific site.

        Args:
            site_id: Competitor site ID
        """
        self.client.delete(
            collection_name=self.CONTENT_SECTIONS,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="site_id",
                        match=MatchValue(value=site_id)
                    )
                ]
            )
        )
        logger.info(f"Deleted all sections for site {site_id}")

    def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics for the content_sections collection"""
        info = self.client.get_collection(self.CONTENT_SECTIONS)
        return {
            "vectors_count": info.vectors_count,
            "indexed_vectors_count": info.indexed_vectors_count,
            "points_count": info.points_count,
            "status": info.status
        }

    def health_check(self) -> bool:
        """Check if Qdrant is accessible"""
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False


# Singleton instance
_section_embedder_instance = None


def get_section_embedder() -> SectionEmbedder:
    """Get or create singleton SectionEmbedder instance"""
    global _section_embedder_instance
    if _section_embedder_instance is None:
        _section_embedder_instance = SectionEmbedder()
    return _section_embedder_instance


def main():
    """Demo: Test section embedding"""
    logger.info("=" * 80)
    logger.info("Section Embedder Demo")
    logger.info("=" * 80)

    embedder = get_section_embedder()

    # Initialize collection
    embedder.initialize_collection()

    # Sample sections
    sections = [
        {
            'heading': 'Residential Pressure Washing',
            'heading_level': 'h2',
            'content': 'We specialize in residential pressure washing services including driveways, patios, decks, and house exteriors. Our team uses professional-grade equipment to remove dirt, grime, and mildew.',
            'word_count': 28
        },
        {
            'heading': 'Commercial Services',
            'heading_level': 'h2',
            'content': 'Our commercial pressure washing services cover parking lots, building exteriors, and sidewalks. We work with businesses of all sizes to maintain clean, professional-looking properties.',
            'word_count': 26
        },
        {
            'heading': 'Why Choose Us',
            'heading_level': 'h2',
            'content': 'With over 10 years of experience, we deliver exceptional results. Our licensed and insured team uses eco-friendly cleaning solutions. Customer satisfaction is our top priority.',
            'word_count': 28
        }
    ]

    # Embed and store
    count = embedder.embed_and_store_sections(
        page_id=999,
        site_id=1,
        url="https://example.com/services",
        page_type="services",
        sections=sections
    )

    logger.info(f"Stored {count} sections")

    # Search for similar sections
    logger.info("\nSearching for 'residential cleaning services'...")
    results = embedder.search_similar_sections(
        query_text="residential cleaning services",
        limit=3
    )

    for result in results:
        logger.info(f"\n  Score: {result['score']:.4f}")
        logger.info(f"  Heading: {result['heading']}")
        logger.info(f"  Preview: {result['content_preview'][:100]}...")

    # Get stats
    stats = embedder.get_collection_stats()
    logger.info(f"\nCollection stats: {stats['points_count']} sections indexed")

    logger.info("\n" + "=" * 80)
    logger.info("Demo Complete")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
