"""
Topic Clustering Service

Groups keywords into semantic clusters for content strategy.
Uses text-based similarity without external APIs.

Clustering Methods:
- Word overlap similarity (Jaccard)
- N-gram similarity
- Prefix/suffix grouping
- Intent-based grouping
- Modifier extraction

Usage:
    from seo_intelligence.services.topic_clusterer import TopicClusterer

    clusterer = TopicClusterer()
    clusters = clusterer.cluster_keywords([
        "car wash near me",
        "car wash prices",
        "auto detailing services",
        "car wash coupons"
    ])

Clusters are stored in the topic_clusters database table.
"""

import re
import math
from collections import defaultdict
from typing import Dict, Any, Optional, List, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from runner.logging_setup import get_logger


class ClusterType(Enum):
    """Types of keyword clusters."""
    TOPIC = "TOPIC"           # Same core topic
    INTENT = "INTENT"         # Same search intent
    MODIFIER = "MODIFIER"     # Same modifier pattern
    QUESTION = "QUESTION"     # Question-based keywords
    LOCATION = "LOCATION"     # Location-based keywords


@dataclass
class TopicCluster:
    """Represents a cluster of related keywords."""
    cluster_id: str
    name: str
    cluster_type: ClusterType
    pillar_keyword: str  # Main/head keyword
    keywords: List[str]
    keyword_count: int
    avg_similarity: float
    modifiers: List[str] = field(default_factory=list)
    questions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "cluster_id": self.cluster_id,
            "name": self.name,
            "type": self.cluster_type.value,
            "pillar_keyword": self.pillar_keyword,
            "keywords": self.keywords,
            "keyword_count": self.keyword_count,
            "avg_similarity": self.avg_similarity,
            "modifiers": self.modifiers,
            "questions": self.questions,
        }


class TopicClusterer:
    """
    Groups keywords into semantic clusters.

    Uses text-based similarity measures without external APIs.
    """

    # Common stop words to ignore in similarity
    STOP_WORDS = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "must", "shall", "can", "need",
        "it", "its", "this", "that", "these", "those", "i", "you", "he",
        "she", "we", "they", "what", "which", "who", "whom", "when", "where",
        "why", "how", "all", "each", "every", "both", "few", "more", "most",
        "other", "some", "such", "no", "nor", "not", "only", "own", "same",
        "so", "than", "too", "very", "just", "also",
    }

    # Question indicators
    QUESTION_STARTERS = [
        "what", "how", "why", "when", "where", "who", "which",
        "can", "does", "is", "are", "should", "will", "do",
    ]

    # Location indicators
    LOCATION_INDICATORS = [
        "near me", "nearby", "in ", "near ", "around ",
        "local", "closest", " city", " state", " county",
    ]

    # Common modifiers
    COMMON_MODIFIERS = [
        "best", "top", "cheap", "free", "online", "professional",
        "near me", "reviews", "cost", "price", "services", "tips",
        "guide", "vs", "versus", "alternative", "comparison",
    ]

    def __init__(self, similarity_threshold: float = 0.3):
        """
        Initialize topic clusterer.

        Args:
            similarity_threshold: Minimum similarity to group keywords (0-1)
        """
        self.similarity_threshold = similarity_threshold
        self.logger = get_logger("topic_clusterer")

    def _tokenize(self, text: str) -> Set[str]:
        """
        Tokenize text into words, removing stop words.

        Args:
            text: Text to tokenize

        Returns:
            set: Unique tokens
        """
        # Lowercase and split on non-alphanumeric
        words = re.findall(r'\b[a-z]+\b', text.lower())

        # Remove stop words
        tokens = {w for w in words if w not in self.STOP_WORDS and len(w) > 1}

        return tokens

    def _get_ngrams(self, text: str, n: int = 2) -> Set[str]:
        """
        Get character n-grams from text.

        Args:
            text: Input text
            n: N-gram size

        Returns:
            set: N-grams
        """
        text = text.lower().replace(" ", "_")
        return {text[i:i+n] for i in range(len(text) - n + 1)}

    def _jaccard_similarity(self, set1: Set[str], set2: Set[str]) -> float:
        """
        Calculate Jaccard similarity between two sets.

        Args:
            set1: First set
            set2: Second set

        Returns:
            float: Similarity score (0-1)
        """
        if not set1 or not set2:
            return 0.0

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        return intersection / union if union > 0 else 0.0

    def _calculate_similarity(self, kw1: str, kw2: str) -> float:
        """
        Calculate overall similarity between two keywords.

        Combines word overlap and n-gram similarity.

        Args:
            kw1: First keyword
            kw2: Second keyword

        Returns:
            float: Similarity score (0-1)
        """
        # Word-based Jaccard similarity
        tokens1 = self._tokenize(kw1)
        tokens2 = self._tokenize(kw2)
        word_sim = self._jaccard_similarity(tokens1, tokens2)

        # N-gram similarity (captures partial word matches)
        ngrams1 = self._get_ngrams(kw1, 3)
        ngrams2 = self._get_ngrams(kw2, 3)
        ngram_sim = self._jaccard_similarity(ngrams1, ngrams2)

        # Weighted combination (word overlap more important)
        combined = (word_sim * 0.7) + (ngram_sim * 0.3)

        return combined

    def _extract_core_topic(self, keyword: str) -> str:
        """
        Extract the core topic from a keyword.

        Removes modifiers, questions words, and location indicators.

        Args:
            keyword: Full keyword

        Returns:
            str: Core topic
        """
        text = keyword.lower()

        # Remove question starters
        for starter in self.QUESTION_STARTERS:
            if text.startswith(starter + " "):
                text = text[len(starter) + 1:]

        # Remove common modifiers
        for modifier in self.COMMON_MODIFIERS:
            text = text.replace(modifier, "").strip()

        # Remove location indicators
        for loc in self.LOCATION_INDICATORS:
            text = text.replace(loc, "").strip()

        # Clean up extra spaces
        text = " ".join(text.split())

        return text if text else keyword.lower()

    def _is_question(self, keyword: str) -> bool:
        """Check if keyword is a question."""
        kw_lower = keyword.lower()
        return any(kw_lower.startswith(q + " ") for q in self.QUESTION_STARTERS)

    def _is_location_based(self, keyword: str) -> bool:
        """Check if keyword has location intent."""
        kw_lower = keyword.lower()
        return any(loc in kw_lower for loc in self.LOCATION_INDICATORS)

    def _extract_modifiers(self, keywords: List[str], core_topic: str) -> List[str]:
        """
        Extract unique modifiers from a set of keywords.

        Args:
            keywords: List of keywords
            core_topic: Core topic to remove

        Returns:
            list: Unique modifiers found
        """
        modifiers = set()
        core_words = set(core_topic.lower().split())

        for kw in keywords:
            words = set(kw.lower().split())
            # Modifiers are words not in core topic
            mods = words - core_words - self.STOP_WORDS
            modifiers.update(mods)

        return sorted(modifiers)

    def _find_pillar_keyword(self, keywords: List[str]) -> str:
        """
        Find the best pillar (head) keyword for a cluster.

        Prefers shorter, more general keywords.

        Args:
            keywords: List of keywords in cluster

        Returns:
            str: Best pillar keyword
        """
        if not keywords:
            return ""

        # Score keywords: shorter + non-question + no modifiers = better pillar
        scored = []
        for kw in keywords:
            score = 0

            # Prefer shorter keywords
            word_count = len(kw.split())
            score -= word_count * 10

            # Penalize questions
            if self._is_question(kw):
                score -= 20

            # Penalize location-based
            if self._is_location_based(kw):
                score -= 10

            # Penalize modifiers
            for mod in self.COMMON_MODIFIERS:
                if mod in kw.lower():
                    score -= 5

            scored.append((kw, score))

        # Return highest scoring keyword
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]

    def _build_similarity_matrix(
        self,
        keywords: List[str],
    ) -> Dict[Tuple[int, int], float]:
        """
        Build similarity matrix for all keyword pairs.

        Args:
            keywords: List of keywords

        Returns:
            dict: (i, j) -> similarity score
        """
        matrix = {}
        n = len(keywords)

        for i in range(n):
            for j in range(i + 1, n):
                sim = self._calculate_similarity(keywords[i], keywords[j])
                matrix[(i, j)] = sim
                matrix[(j, i)] = sim

        return matrix

    def cluster_keywords(
        self,
        keywords: List[str],
        min_cluster_size: int = 2,
    ) -> List[TopicCluster]:
        """
        Cluster keywords into topic groups.

        Uses agglomerative clustering based on similarity.

        Args:
            keywords: Keywords to cluster
            min_cluster_size: Minimum keywords per cluster

        Returns:
            list: TopicCluster objects
        """
        if not keywords:
            return []

        # Deduplicate and normalize
        keywords = list(set(kw.strip().lower() for kw in keywords if kw.strip()))

        if len(keywords) < min_cluster_size:
            return []

        self.logger.info(f"Clustering {len(keywords)} keywords...")

        # Build similarity matrix
        sim_matrix = self._build_similarity_matrix(keywords)

        # Initialize: each keyword in its own cluster
        clusters: Dict[int, Set[int]] = {i: {i} for i in range(len(keywords))}
        cluster_map = {i: i for i in range(len(keywords))}  # keyword index -> cluster id

        # Agglomerative clustering
        # Merge clusters until no pairs exceed threshold
        changed = True
        while changed:
            changed = False
            best_sim = 0
            best_pair = None

            # Find most similar cluster pair
            cluster_ids = list(set(cluster_map.values()))

            for i, c1 in enumerate(cluster_ids):
                for c2 in cluster_ids[i + 1:]:
                    if c1 == c2:
                        continue

                    # Average linkage: mean similarity between all pairs
                    similarities = []
                    for kw1_idx in clusters[c1]:
                        for kw2_idx in clusters[c2]:
                            key = (min(kw1_idx, kw2_idx), max(kw1_idx, kw2_idx))
                            if key in sim_matrix:
                                similarities.append(sim_matrix[key])

                    if similarities:
                        avg_sim = sum(similarities) / len(similarities)
                        if avg_sim > best_sim and avg_sim >= self.similarity_threshold:
                            best_sim = avg_sim
                            best_pair = (c1, c2)

            # Merge best pair
            if best_pair:
                c1, c2 = best_pair
                clusters[c1].update(clusters[c2])

                # Update cluster map
                for kw_idx in clusters[c2]:
                    cluster_map[kw_idx] = c1

                del clusters[c2]
                changed = True

        # Convert to TopicCluster objects
        result_clusters = []
        cluster_num = 0

        for cluster_id, kw_indices in clusters.items():
            if len(kw_indices) < min_cluster_size:
                continue

            cluster_keywords = [keywords[i] for i in kw_indices]

            # Find pillar keyword
            pillar = self._find_pillar_keyword(cluster_keywords)

            # Extract core topic
            core_topic = self._extract_core_topic(pillar)

            # Calculate average similarity within cluster
            sims = []
            kw_list = list(kw_indices)
            for i, idx1 in enumerate(kw_list):
                for idx2 in kw_list[i + 1:]:
                    key = (min(idx1, idx2), max(idx1, idx2))
                    if key in sim_matrix:
                        sims.append(sim_matrix[key])

            avg_sim = sum(sims) / len(sims) if sims else 0

            # Extract modifiers and questions
            modifiers = self._extract_modifiers(cluster_keywords, core_topic)
            questions = [kw for kw in cluster_keywords if self._is_question(kw)]

            # Determine cluster type
            if all(self._is_question(kw) for kw in cluster_keywords):
                cluster_type = ClusterType.QUESTION
            elif all(self._is_location_based(kw) for kw in cluster_keywords):
                cluster_type = ClusterType.LOCATION
            else:
                cluster_type = ClusterType.TOPIC

            cluster_num += 1
            cluster = TopicCluster(
                cluster_id=f"cluster_{cluster_num}",
                name=core_topic or pillar,
                cluster_type=cluster_type,
                pillar_keyword=pillar,
                keywords=sorted(cluster_keywords),
                keyword_count=len(cluster_keywords),
                avg_similarity=round(avg_sim, 3),
                modifiers=modifiers[:10],
                questions=questions[:5],
            )

            result_clusters.append(cluster)

        # Sort by cluster size descending
        result_clusters.sort(key=lambda x: x.keyword_count, reverse=True)

        self.logger.info(
            f"Created {len(result_clusters)} clusters from {len(keywords)} keywords"
        )

        return result_clusters

    def cluster_by_intent(
        self,
        keywords: List[str],
    ) -> Dict[str, List[str]]:
        """
        Group keywords by search intent.

        Args:
            keywords: Keywords to group

        Returns:
            dict: Intent -> list of keywords
        """
        from seo_intelligence.services.opportunity_analyzer import SearchIntent

        intent_groups = {intent.value: [] for intent in SearchIntent}

        # Intent indicators (from opportunity_analyzer)
        intent_indicators = {
            "TRANSACTIONAL": [
                "buy", "purchase", "order", "price", "cost", "cheap",
                "deal", "discount", "coupon", "sale", "shop", "store",
            ],
            "COMMERCIAL": [
                "best", "top", "review", "reviews", "comparison", "vs",
                "versus", "alternative", "compare", "rated",
            ],
            "INFORMATIONAL": [
                "what is", "what are", "how to", "how do", "why",
                "when", "where", "who", "guide", "tutorial", "learn",
            ],
            "NAVIGATIONAL": [
                "login", "sign in", "website", "official", "portal",
            ],
            "LOCAL": [
                "near me", "nearby", "local", "closest", "directions",
            ],
        }

        for kw in keywords:
            kw_lower = kw.lower()
            classified = False

            for intent, indicators in intent_indicators.items():
                if any(ind in kw_lower for ind in indicators):
                    intent_groups[intent].append(kw)
                    classified = True
                    break

            if not classified:
                intent_groups["INFORMATIONAL"].append(kw)

        # Remove empty groups
        return {k: v for k, v in intent_groups.items() if v}

    def generate_content_pillars(
        self,
        clusters: List[TopicCluster],
    ) -> List[Dict[str, Any]]:
        """
        Generate content pillar strategy from clusters.

        Args:
            clusters: Topic clusters

        Returns:
            list: Content pillar recommendations
        """
        pillars = []

        for cluster in clusters:
            pillar = {
                "pillar_topic": cluster.name,
                "main_keyword": cluster.pillar_keyword,
                "supporting_keywords": [
                    kw for kw in cluster.keywords
                    if kw != cluster.pillar_keyword
                ][:10],
                "content_ideas": [],
                "cluster_size": cluster.keyword_count,
            }

            # Generate content ideas
            # Main pillar page
            pillar["content_ideas"].append({
                "type": "pillar_page",
                "title": f"Complete Guide to {cluster.name.title()}",
                "target_keyword": cluster.pillar_keyword,
            })

            # Supporting articles from modifiers
            for modifier in cluster.modifiers[:5]:
                pillar["content_ideas"].append({
                    "type": "supporting_article",
                    "title": f"{cluster.name.title()} {modifier.title()}",
                    "target_keyword": f"{cluster.name} {modifier}",
                })

            # FAQ pages from questions
            if cluster.questions:
                pillar["content_ideas"].append({
                    "type": "faq_page",
                    "title": f"{cluster.name.title()} FAQ",
                    "questions": cluster.questions,
                })

            pillars.append(pillar)

        return pillars

    def save_clusters(
        self,
        clusters: List[TopicCluster],
        competitor_id: Optional[int] = None,
    ):
        """
        Save clusters to database.

        Args:
            clusters: Clusters to save
            competitor_id: Optional competitor association
        """
        if not clusters:
            return

        import json
        from sqlalchemy import create_engine, text
        from dotenv import load_dotenv
        import os

        load_dotenv()
        db_url = os.getenv("DATABASE_URL")

        if not db_url:
            self.logger.warning("DATABASE_URL not set, skipping save")
            return

        engine = create_engine(db_url)

        insert_sql = text("""
            INSERT INTO topic_clusters (
                cluster_name, pillar_keyword, keywords,
                keyword_count, cluster_type, avg_similarity,
                competitor_id, metadata, created_at
            ) VALUES (
                :name, :pillar, :keywords,
                :count, :type, :similarity,
                :competitor_id, :metadata, :created_at
            )
            ON CONFLICT (cluster_name, pillar_keyword) DO UPDATE SET
                keywords = EXCLUDED.keywords,
                keyword_count = EXCLUDED.keyword_count,
                avg_similarity = EXCLUDED.avg_similarity,
                updated_at = NOW()
        """)

        with engine.connect() as conn:
            for cluster in clusters:
                try:
                    conn.execute(insert_sql, {
                        "name": cluster.name,
                        "pillar": cluster.pillar_keyword,
                        "keywords": json.dumps(cluster.keywords),
                        "count": cluster.keyword_count,
                        "type": cluster.cluster_type.value,
                        "similarity": cluster.avg_similarity,
                        "competitor_id": competitor_id,
                        "metadata": json.dumps({
                            "modifiers": cluster.modifiers,
                            "questions": cluster.questions,
                        }),
                        "created_at": cluster.created_at,
                    })
                except Exception as e:
                    self.logger.debug(f"Error saving cluster: {e}")

            conn.commit()

        self.logger.info(f"Saved {len(clusters)} clusters to database")


# Module-level singleton
_topic_clusterer_instance = None


def get_topic_clusterer() -> TopicClusterer:
    """Get or create the singleton TopicClusterer instance."""
    global _topic_clusterer_instance

    if _topic_clusterer_instance is None:
        _topic_clusterer_instance = TopicClusterer()

    return _topic_clusterer_instance
