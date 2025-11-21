"""
Embedding Generation Service

Handles text chunking and embedding generation for competitor pages and SERP snippets.

Per SCRAPER BOT.pdf specification:
- Chunk main content ~1k tokens
- Generate embeddings using sentence-transformers (local) or OpenAI
- Record model and embedding version
- Support quarterly re-embedding

Uses sentence-transformers for local embedding generation (no API costs).
"""

import os
import re
from typing import List, Dict, Any, Tuple
import tiktoken

from sentence_transformers import SentenceTransformer


class TextChunker:
    """
    Chunks text into manageable pieces for embedding.

    Per spec: ~1k tokens per chunk with overlap for context preservation.
    """

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        """
        Initialize chunker with token limits.

        Args:
            chunk_size: Maximum tokens per chunk
            chunk_overlap: Overlapping tokens between chunks
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Use cl100k_base encoding (GPT-3.5/GPT-4)
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            # Fallback if tiktoken unavailable
            self.tokenizer = None

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text"""
        if self.tokenizer:
            return len(self.tokenizer.encode(text))
        else:
            # Rough approximation: 1 token ≈ 4 characters
            return len(text) // 4

    def _split_by_tokens(self, text: str) -> List[str]:
        """Split text into token-sized chunks"""
        if not self.tokenizer:
            # Fallback: split by characters
            char_size = self.chunk_size * 4
            overlap_chars = self.chunk_overlap * 4
            chunks = []
            for i in range(0, len(text), char_size - overlap_chars):
                chunks.append(text[i:i + char_size])
            return chunks

        tokens = self.tokenizer.encode(text)
        chunks = []

        for i in range(0, len(tokens), self.chunk_size - self.chunk_overlap):
            chunk_tokens = tokens[i:i + self.chunk_size]
            chunk_text = self.tokenizer.decode(chunk_tokens)
            chunks.append(chunk_text)

        return chunks

    def chunk_text(self, text: str) -> List[str]:
        """
        Chunk text into manageable pieces.

        Args:
            text: Input text to chunk

        Returns:
            List of text chunks
        """
        # Clean text
        text = self._clean_text(text)

        # If text is small enough, return as single chunk
        if self._count_tokens(text) <= self.chunk_size:
            return [text] if text.strip() else []

        # Split by tokens
        return self._split_by_tokens(text)

    def _clean_text(self, text: str) -> str:
        """
        Clean text before chunking.

        Removes excessive whitespace, normalizes line breaks.
        """
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove leading/trailing whitespace
        text = text.strip()
        return text


class EmbeddingGenerator:
    """
    Generates embeddings using sentence-transformers.

    Uses all-MiniLM-L6-v2 by default (384 dimensions, good balance of speed/quality).
    Alternative models:
    - all-mpnet-base-v2 (768 dims, higher quality, slower)
    - all-MiniLM-L12-v2 (384 dims, good quality)
    """

    def __init__(self, model_name: str = None):
        """
        Initialize embedding generator.

        Args:
            model_name: Sentence-transformer model name
        """
        self.model_name = model_name or os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        self.embedding_version = os.getenv("EMBEDDING_VERSION", "v1.0")

        # Load model
        print(f"Loading embedding model: {self.model_name}")
        self.model = SentenceTransformer(self.model_name)

        # Get embedding dimension
        self.dimension = self.model.get_sentence_embedding_dimension()
        print(f"✓ Model loaded. Embedding dimension: {self.dimension}")

    def embed_text(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Input text

        Returns:
            Embedding vector as list of floats
        """
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts (more efficient).

        Args:
            texts: List of input texts

        Returns:
            List of embedding vectors
        """
        embeddings = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=True)
        return embeddings.tolist()

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the current model"""
        return {
            "model_name": self.model_name,
            "embedding_version": self.embedding_version,
            "dimension": self.dimension,
            "max_seq_length": self.model.max_seq_length
        }


class ContentEmbedder:
    """
    High-level service combining chunking and embedding.

    Handles the full pipeline from raw text to embedded chunks.
    """

    def __init__(self):
        """Initialize chunker and embedding generator"""
        chunk_size = int(os.getenv("CHUNK_SIZE", 1000))
        chunk_overlap = int(os.getenv("CHUNK_OVERLAP", 200))

        self.chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.embedder = EmbeddingGenerator()

    def embed_content(self, content: str) -> Tuple[List[str], List[List[float]]]:
        """
        Chunk and embed content.

        Args:
            content: Raw text content

        Returns:
            Tuple of (chunks, embeddings)
        """
        # Chunk content
        chunks = self.chunker.chunk_text(content)

        if not chunks:
            return [], []

        # Generate embeddings
        embeddings = self.embedder.embed_batch(chunks)

        return chunks, embeddings

    def embed_single(self, text: str) -> List[float]:
        """
        Embed a single piece of text without chunking.

        Useful for short texts like SERP snippets.

        Args:
            text: Input text

        Returns:
            Embedding vector
        """
        return self.embedder.embed_text(text)

    def get_info(self) -> Dict[str, Any]:
        """Get embedder configuration info"""
        return {
            **self.embedder.get_model_info(),
            "chunk_size": self.chunker.chunk_size,
            "chunk_overlap": self.chunker.chunk_overlap
        }


# Singleton instance
_content_embedder = None


def get_content_embedder() -> ContentEmbedder:
    """Get or create singleton content embedder instance"""
    global _content_embedder
    if _content_embedder is None:
        _content_embedder = ContentEmbedder()
    return _content_embedder


def extract_main_content(html_content: str, boilerplate_selectors: List[str] = None) -> str:
    """
    Extract main content from HTML, removing boilerplate.

    Per spec: Extract cleaned main text after boilerplate removal.

    Args:
        html_content: Raw HTML
        boilerplate_selectors: CSS selectors for elements to remove

    Returns:
        Cleaned main text
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, 'lxml')

    # Default boilerplate selectors
    if boilerplate_selectors is None:
        boilerplate_selectors = [
            'nav', 'header', 'footer', 'aside',
            '.nav', '.header', '.footer', '.sidebar',
            '#nav', '#header', '#footer', '#sidebar',
            '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]'
        ]

    # Remove boilerplate elements
    for selector in boilerplate_selectors:
        for element in soup.select(selector):
            element.decompose()

    # Try to find main content
    main_content = None

    # Look for <main> or <article> tags
    main_tag = soup.find('main') or soup.find('article')
    if main_tag:
        main_content = main_tag.get_text(separator=' ', strip=True)
    else:
        # Fallback: get all text from body
        body = soup.find('body')
        if body:
            main_content = body.get_text(separator=' ', strip=True)
        else:
            main_content = soup.get_text(separator=' ', strip=True)

    return main_content
