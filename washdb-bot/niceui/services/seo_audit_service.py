"""
SEO Audit Service
Integrates backend SEO extractors with the GUI
"""

import logging
import sys
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import backend SEO extractors
from seo_extractors.lighthouse_runner import LighthouseRunner
from seo_extractors.technical_seo_extractor import TechnicalSEOExtractor
from seo_extractors.content_intelligence import ContentIntelligenceExtractor
from seo_extractors.onpage_seo_analyzer import OnPageSEOAnalyzer

logger = logging.getLogger(__name__)


class SEOAuditService:
    """
    Service layer for SEO auditing
    Coordinates multiple SEO extractors and returns unified results
    """

    def __init__(self):
        """Initialize all SEO extractors"""
        self.lighthouse_runner = LighthouseRunner()
        self.technical_seo = TechnicalSEOExtractor()
        self.content_intelligence = ContentIntelligenceExtractor()
        self.onpage_analyzer = OnPageSEOAnalyzer()
        self.executor = ThreadPoolExecutor(max_workers=4)

    async def run_full_audit(self, url: str, device_type: str = 'desktop') -> Dict[str, Any]:
        """
        Run a comprehensive SEO audit on the given URL

        Args:
            url: Target URL to audit
            device_type: 'desktop' or 'mobile'

        Returns:
            Dictionary with all audit results
        """
        logger.info(f"Starting full SEO audit for: {url}")

        audit_results = {
            'url': url,
            'device_type': device_type,
            'timestamp': datetime.now().isoformat(),
            'status': 'running',
            'lighthouse': None,
            'technical_seo': None,
            'content': None,
            'onpage': None,
            'errors': []
        }

        try:
            # Run all audits in parallel
            loop = asyncio.get_event_loop()

            # Run Lighthouse audit
            lighthouse_task = loop.run_in_executor(
                self.executor,
                self._run_lighthouse,
                url,
                device_type
            )

            # Run Technical SEO audit
            technical_task = loop.run_in_executor(
                self.executor,
                self._run_technical_seo,
                url
            )

            # Run Content Intelligence
            content_task = loop.run_in_executor(
                self.executor,
                self._run_content_intelligence,
                url
            )

            # Run On-Page SEO audit
            onpage_task = loop.run_in_executor(
                self.executor,
                self._run_onpage_seo,
                url
            )

            # Wait for all tasks to complete
            results = await asyncio.gather(
                lighthouse_task,
                technical_task,
                content_task,
                onpage_task,
                return_exceptions=True
            )

            # Process results
            audit_results['lighthouse'] = results[0] if not isinstance(results[0], Exception) else None
            audit_results['technical_seo'] = results[1] if not isinstance(results[1], Exception) else None
            audit_results['content'] = results[2] if not isinstance(results[2], Exception) else None
            audit_results['onpage'] = results[3] if not isinstance(results[3], Exception) else None

            # Collect errors
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    audit_name = ['Lighthouse', 'Technical SEO', 'Content', 'On-Page'][i]
                    error_msg = f"{audit_name}: {str(result)}"
                    audit_results['errors'].append(error_msg)
                    logger.error(error_msg)

            audit_results['status'] = 'completed' if not all(isinstance(r, Exception) for r in results) else 'failed'

        except Exception as e:
            logger.error(f"Full audit failed: {e}")
            audit_results['status'] = 'failed'
            audit_results['errors'].append(str(e))

        logger.info(f"SEO audit completed for: {url} - Status: {audit_results['status']}")
        return audit_results

    def _run_lighthouse(self, url: str, device_type: str) -> Optional[Dict]:
        """Run Lighthouse audit"""
        try:
            logger.info(f"Running Lighthouse audit for {url}")
            result = self.lighthouse_runner.run_audit(url, device_type=device_type)

            if result and result.success:
                return {
                    'success': True,
                    'scores': {
                        'performance': result.scores.performance_score,
                        'accessibility': result.scores.accessibility_score,
                        'seo': result.scores.seo_score,
                        'best_practices': result.scores.best_practices_score,
                        'pwa': result.scores.pwa_score
                    },
                    'core_web_vitals': {
                        'lcp': result.core_web_vitals.lcp_score,
                        'fid': result.core_web_vitals.fid_score,
                        'cls': result.core_web_vitals.cls_score,
                        'inp': result.core_web_vitals.inp_score,
                        'ttfb': result.core_web_vitals.ttfb_score
                    },
                    'timing': {
                        'fcp': result.timing_metrics.first_contentful_paint,
                        'speed_index': result.timing_metrics.speed_index,
                        'tti': result.timing_metrics.time_to_interactive,
                        'tbt': result.timing_metrics.total_blocking_time
                    },
                    'resources': {
                        'page_size_kb': result.resource_metrics.total_page_size_kb,
                        'total_requests': result.resource_metrics.total_requests
                    }
                }
            else:
                return {'success': False, 'error': result.error if result else 'Unknown error'}

        except Exception as e:
            logger.error(f"Lighthouse audit failed: {e}")
            raise

    def _run_technical_seo(self, url: str) -> Optional[Dict]:
        """Run Technical SEO audit"""
        try:
            logger.info(f"Running Technical SEO audit for {url}")
            result = self.technical_seo.analyze(url)

            if result and result.success:
                return {
                    'success': True,
                    'ssl': {
                        'has_https': result.ssl_info.has_https,
                        'ssl_valid': result.ssl_info.ssl_valid,
                        'ssl_issuer': result.ssl_info.ssl_issuer,
                        'ssl_expiry_days': result.ssl_info.ssl_expiry_days,
                        'mixed_content': result.ssl_info.mixed_content
                    },
                    'canonical': {
                        'has_canonical': result.canonical_info.has_canonical,
                        'canonical_url': result.canonical_info.canonical_url,
                        'is_self_canonical': result.canonical_info.is_self_canonical,
                        'chain_length': result.canonical_info.canonical_chain_length
                    },
                    'redirects': {
                        'has_redirects': result.redirect_info.has_redirects,
                        'redirect_count': result.redirect_info.redirect_count,
                        'redirect_type': result.redirect_info.redirect_type
                    },
                    'schema': {
                        'has_schema': result.schema_info.has_schema,
                        'schema_types': result.schema_info.schema_types,
                        'schema_count': result.schema_info.schema_count,
                        'valid_json_ld': result.schema_info.valid_json_ld
                    },
                    'indexability': {
                        'is_noindex': result.indexability_info.is_noindex,
                        'is_nofollow': result.indexability_info.is_nofollow,
                        'robots_txt_allows': result.indexability_info.robots_txt_allows,
                        'sitemap_present': result.indexability_info.sitemap_present
                    },
                    'mobile': {
                        'has_viewport_meta': result.mobile_info.has_viewport_meta,
                        'viewport_content': result.mobile_info.viewport_content
                    }
                }
            else:
                return {'success': False, 'error': result.error if result else 'Unknown error'}

        except Exception as e:
            logger.error(f"Technical SEO audit failed: {e}")
            raise

    def _run_content_intelligence(self, url: str) -> Optional[Dict]:
        """Run Content Intelligence audit"""
        try:
            logger.info(f"Running Content Intelligence for {url}")
            result = self.content_intelligence.analyze(url)

            if result and result.success:
                return {
                    'success': True,
                    'stats': {
                        'word_count': result.content_stats.word_count,
                        'character_count': result.content_stats.character_count,
                        'paragraph_count': result.content_stats.paragraph_count,
                        'sentence_count': result.content_stats.sentence_count,
                        'avg_words_per_sentence': result.content_stats.avg_words_per_sentence,
                        'content_to_html_ratio': result.content_stats.content_to_html_ratio
                    },
                    'readability': {
                        'flesch_reading_ease': result.readability_scores.flesch_reading_ease,
                        'flesch_kincaid_grade': result.readability_scores.flesch_kincaid_grade,
                        'smog_index': result.readability_scores.smog_index,
                        'difficult_words': result.readability_scores.difficult_words_count
                    },
                    'keywords': {
                        'top_keywords': result.keyword_metrics.top_keywords,
                        'keyword_density': result.keyword_metrics.keyword_density,
                        'top_bigrams': result.keyword_metrics.top_bigrams
                    },
                    'eat_signals': {
                        'has_author_bio': result.eat_signals.has_author_bio,
                        'author_name': result.eat_signals.author_name,
                        'has_publish_date': result.eat_signals.has_publish_date,
                        'publish_date': result.eat_signals.publish_date,
                        'external_links_count': result.eat_signals.external_links_count
                    },
                    'quality': {
                        'content_depth_score': result.content_quality.content_depth_score,
                        'has_images': result.content_quality.has_images,
                        'image_count': result.content_quality.image_count,
                        'has_videos': result.content_quality.has_videos,
                        'video_count': result.content_quality.video_count
                    }
                }
            else:
                return {'success': False, 'error': result.error if result else 'Unknown error'}

        except Exception as e:
            logger.error(f"Content Intelligence failed: {e}")
            raise

    def _run_onpage_seo(self, url: str) -> Optional[Dict]:
        """Run On-Page SEO audit"""
        try:
            logger.info(f"Running On-Page SEO audit for {url}")
            result = self.onpage_analyzer.analyze(url)

            if result and result.success:
                return {
                    'success': True,
                    'title': {
                        'has_title': result.title_metrics.has_title,
                        'title_text': result.title_metrics.title_text,
                        'title_length': result.title_metrics.title_length,
                        'title_optimal': result.title_metrics.title_optimal
                    },
                    'meta_description': {
                        'has_meta_description': result.meta_description.has_meta_description,
                        'description_text': result.meta_description.description_text,
                        'description_length': result.meta_description.description_length,
                        'description_optimal': result.meta_description.description_optimal
                    },
                    'headers': {
                        'has_h1': result.header_analysis.has_h1,
                        'h1_text': result.header_analysis.h1_text,
                        'h1_count': result.header_analysis.h1_count,
                        'h2_count': result.header_analysis.h2_count,
                        'h3_count': result.header_analysis.h3_count
                    },
                    'images': {
                        'total_images': result.image_optimization.total_images,
                        'images_with_alt': result.image_optimization.images_with_alt,
                        'images_missing_alt': result.image_optimization.images_missing_alt,
                        'alt_text_quality_score': result.image_optimization.alt_text_quality_score
                    },
                    'internal_links': {
                        'total': result.internal_linking.total_internal_links,
                        'unique': result.internal_linking.unique_internal_links,
                        'with_anchor': result.internal_linking.internal_links_with_anchor
                    },
                    'external_links': {
                        'total': result.external_linking.total_external_links,
                        'unique_domains': result.external_linking.unique_external_domains,
                        'dofollow': result.external_linking.dofollow_links,
                        'nofollow': result.external_linking.nofollow_links
                    }
                }
            else:
                return {'success': False, 'error': result.error if result else 'Unknown error'}

        except Exception as e:
            logger.error(f"On-Page SEO audit failed: {e}")
            raise

    def cleanup(self):
        """Cleanup resources"""
        self.executor.shutdown(wait=True)
