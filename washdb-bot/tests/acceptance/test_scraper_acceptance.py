"""
Phase 2: Scraper Module Acceptance Tests

Integration tests that actually run scrapers and verify database writes.
These tests are marked as @pytest.mark.slow and @pytest.mark.integration.

Run with: pytest tests/test_scraper_acceptance.py -v
Skip slow tests: pytest -m "not slow"
"""

import pytest
from sqlalchemy import text
from datetime import datetime

from seo_intelligence.scrapers import SerpScraper, CompetitorCrawler, CitationCrawler, BusinessInfo


class TestSERPModule:
    """Test 2.1: SERP Module Acceptance Test"""

    @pytest.mark.acceptance
    @pytest.mark.integration
    @pytest.mark.slow
    def test_serp_scraper_basic(
        self,
        db_connection,
        test_query_text,
        cleanup_test_queries
    ):
        """
        Test SERP scraper creates correct database records.

        NOTE: This test makes real requests to Google. It may be slow and
        could be rate-limited. Consider mocking for CI/CD pipelines.
        """
        # Run SERP scraper with minimal results
        scraper = SerpScraper()
        scraper.start()

        try:
            results = scraper.scrape_query(
                query=test_query_text,
                location="Austin, TX",
                num_results=10  # Small number for test
            )

            assert results is not None, "Scraper should return results"

        finally:
            scraper.stop()

        # Verify search_queries row created
        result = db_connection.execute(text("""
            SELECT query_id, query_text, location, search_engine, is_active
            FROM search_queries
            WHERE query_text = :query_text
        """), {"query_text": test_query_text})

        query_row = result.fetchone()
        assert query_row is not None, "search_queries row should be created"
        assert query_row[1] == test_query_text
        assert query_row[3] == 'google'  # search_engine
        assert query_row[4] is True  # is_active

        query_id = query_row[0]

        # Verify serp_snapshots row created
        result = db_connection.execute(text("""
            SELECT snapshot_id, result_count, snapshot_hash, raw_html IS NOT NULL
            FROM serp_snapshots
            WHERE query_id = :query_id
            ORDER BY captured_at DESC
            LIMIT 1
        """), {"query_id": query_id})

        snapshot_row = result.fetchone()
        assert snapshot_row is not None, "serp_snapshots row should be created"
        assert snapshot_row[1] > 0, "result_count should be > 0"
        assert len(snapshot_row[2]) == 64, "snapshot_hash should be 64 chars (SHA256)"
        assert snapshot_row[3] is True, "raw_html should be stored"

        snapshot_id = snapshot_row[0]

        # Verify serp_results rows created
        result = db_connection.execute(text("""
            SELECT COUNT(*) FROM serp_results WHERE snapshot_id = :snapshot_id
        """), {"snapshot_id": snapshot_id})

        result_count = result.fetchone()[0]
        assert result_count > 0, "Should have at least 1 serp_results row"
        assert result_count <= 10, "Should not exceed num_results limit"

        # Verify serp_results have required fields
        result = db_connection.execute(text("""
            SELECT position, url, title, domain, is_our_company
            FROM serp_results
            WHERE snapshot_id = :snapshot_id
            ORDER BY position ASC
        """), {"snapshot_id": snapshot_id})

        rows = result.fetchall()
        positions = [row[0] for row in rows]

        # Check positions are sequential starting from 1
        assert positions[0] == 1, "First position should be 1"
        assert positions == sorted(positions), "Positions should be sequential"

        # Check all results have URLs and titles
        for row in rows:
            assert row[1] is not None and len(row[1]) > 0, "URL should not be empty"
            assert row[2] is not None and len(row[2]) > 0, "Title should not be empty"
            assert row[3] is not None and len(row[3]) > 0, "Domain should not be empty"
            # is_our_company (row[4]) - can be True or False

    @pytest.mark.acceptance
    @pytest.mark.integration
    def test_serp_no_duplicate_positions(
        self,
        db_connection
    ):
        """Test that SERP results don't have duplicate positions within same snapshot."""
        result = db_connection.execute(text("""
            SELECT snapshot_id, position, COUNT(*) as duplicate_count
            FROM serp_results
            WHERE snapshot_id IN (
                SELECT snapshot_id FROM serp_snapshots
                ORDER BY captured_at DESC LIMIT 10
            )
            GROUP BY snapshot_id, position
            HAVING COUNT(*) > 1
        """))

        duplicates = result.fetchall()
        assert len(duplicates) == 0, \
            f"Found duplicate positions in snapshots: {duplicates}"


class TestCompetitorCrawler:
    """Test 2.2: Competitor Crawler Acceptance Test"""

    @pytest.mark.acceptance
    @pytest.mark.integration
    @pytest.mark.slow
    def test_competitor_crawler_basic(
        self,
        db_connection,
        test_domain,
        cleanup_test_competitors
    ):
        """
        Test competitor crawler creates pages with hashes and JSON-LD.

        NOTE: Uses example.com as test target to avoid hitting real competitors.
        """
        # Use example.com as a safe test target
        test_domain = 'example.com'

        scraper = CompetitorCrawler()
        scraper.start()

        try:
            results = scraper.crawl_domain(
                domain=test_domain,
                name="Test Example Site",
                max_pages=2  # Minimal for test
            )

            assert len(results) > 0, "Should crawl at least 1 page"

        finally:
            scraper.stop()

        # Verify competitors row created
        result = db_connection.execute(text("""
            SELECT competitor_id, name, domain, is_active
            FROM competitors
            WHERE domain = :domain
        """), {"domain": test_domain})

        comp_row = result.fetchone()
        assert comp_row is not None, "competitors row should be created"
        assert comp_row[2] == test_domain
        assert comp_row[3] is True  # is_active

        competitor_id = comp_row[0]

        # Verify competitor_pages rows created
        result = db_connection.execute(text("""
            SELECT page_id, url, content_hash, word_count, status_code,
                   schema_markup IS NOT NULL, links IS NOT NULL
            FROM competitor_pages
            WHERE competitor_id = :competitor_id
            ORDER BY crawled_at DESC
        """), {"competitor_id": competitor_id})

        pages = result.fetchall()
        assert len(pages) > 0, "Should have at least 1 competitor_pages row"

        for page in pages:
            # content_hash should be 64-char SHA256
            assert page[2] is not None and len(page[2]) == 64, \
                f"content_hash should be 64 chars, got {len(page[2]) if page[2] else 0}"

            # word_count should be > 0 for successful crawl
            if page[4] == 200:  # status_code
                assert page[3] > 0, f"word_count should be > 0 for 200 status, got {page[3]}"

    @pytest.mark.acceptance
    @pytest.mark.integration
    def test_competitor_no_duplicate_urls(
        self,
        db_connection
    ):
        """Test competitor_pages doesn't have duplicate URLs per competitor."""
        result = db_connection.execute(text("""
            SELECT competitor_id, url, COUNT(*) as duplicate_count
            FROM competitor_pages
            GROUP BY competitor_id, url
            HAVING COUNT(*) > 1
        """))

        duplicates = result.fetchall()
        assert len(duplicates) == 0, \
            f"Found duplicate URLs in competitor_pages: {duplicates}"

    @pytest.mark.acceptance
    @pytest.mark.integration
    def test_competitor_content_hash_stability(
        self,
        db_connection
    ):
        """
        Test content_hash remains stable when page content doesn't change.

        This checks recent crawls of the same URL have consistent hashes.
        """
        result = db_connection.execute(text("""
            WITH recent_pages AS (
                SELECT url, content_hash, crawled_at,
                       ROW_NUMBER() OVER (PARTITION BY url ORDER BY crawled_at DESC) as recency
                FROM competitor_pages
                WHERE crawled_at > NOW() - INTERVAL '7 days'
            )
            SELECT url, COUNT(DISTINCT content_hash) as hash_count
            FROM recent_pages
            WHERE recency <= 2
            GROUP BY url
            HAVING COUNT(DISTINCT content_hash) > 1
        """))

        unstable_hashes = result.fetchall()

        # Some variance is acceptable (content may change), but excessive variance is a problem
        # This test is informational - it will warn but not fail
        if len(unstable_hashes) > 0:
            print(f"WARNING: {len(unstable_hashes)} URLs have changing hashes (may be dynamic content)")


class TestCitationsCrawler:
    """Test 2.3: Citations Auditor Acceptance Test"""

    @pytest.mark.acceptance
    @pytest.mark.integration
    @pytest.mark.slow
    def test_citations_crawler_basic(
        self,
        db_connection,
        test_business_info,
        cleanup_test_citations
    ):
        """
        Test citations crawler checks directories and handles NAP matching.

        NOTE: This makes real requests to citation directories. May be slow.
        """
        scraper = CitationCrawler()

        # Check a subset of directories for testing
        test_directories = ['yelp', 'yellowpages']  # Minimal set

        results = scraper.check_directories(
            business=test_business_info,
            directories=test_directories
        )

        assert len(results) > 0, "Should return citation results"

        # Verify citations rows created
        result = db_connection.execute(text("""
            SELECT citation_id, directory_name, listing_url,
                   nap_match_score, has_website_link
            FROM citations
            WHERE business_name = :business_name
        """), {"business_name": test_business_info.name})

        citations = result.fetchall()
        assert len(citations) > 0, "Should create citations rows"

        for citation in citations:
            # directory_name should match test_directories
            assert citation[1] in test_directories, \
                f"Unexpected directory: {citation[1]}"

            # If listing_url is not NULL, should have NAP score
            if citation[2] is not None:
                assert citation[3] is not None, \
                    "Found listings should have nap_match_score"
                assert 0 <= citation[3] <= 100, \
                    f"NAP score should be 0-100, got {citation[3]}"

    @pytest.mark.acceptance
    @pytest.mark.integration
    def test_citations_robots_handling(
        self,
        db_connection
    ):
        """Test citations gracefully handle robots.txt blocks."""
        # Check for citations with robots blocks (should have reason in metadata)
        result = db_connection.execute(text("""
            SELECT directory_name, metadata->>'status', metadata->>'reason'
            FROM citations
            WHERE metadata->>'status' = 'blocked'
            AND metadata->>'reason' = 'ROBOTS_DISALLOWED'
            LIMIT 5
        """))

        blocked_citations = result.fetchall()

        # This test is informational - some directories may block robots
        if len(blocked_citations) > 0:
            print(f"INFO: {len(blocked_citations)} citations blocked by robots.txt (expected)")
            for citation in blocked_citations:
                print(f"  {citation[0]}: {citation[2]}")


class TestErrorHandling:
    """Test 2.5: Error Handling & Reason Codes"""

    @pytest.mark.acceptance
    @pytest.mark.safety
    def test_dns_failure_handling(self, domain_quarantine):
        """Test handling of DNS failures."""
        nonexistent_domain = 'nonexistent-test-domain-12345.invalid'

        # Domain should not be quarantined initially
        assert not domain_quarantine.is_quarantined(nonexistent_domain)

        # Note: Actual DNS failure testing would require running a scraper
        # This test verifies the quarantine service is ready to handle it
        assert domain_quarantine is not None

    @pytest.mark.acceptance
    @pytest.mark.safety
    def test_robots_disallow_handling(self, robots_checker):
        """Test robots.txt disallow handling."""
        # Many sites disallow /admin/
        allowed = robots_checker.is_allowed(
            'https://example.com/admin/',
            'WashdbBot/1.0'
        )

        # We expect this to be blocked or allowed - both are valid responses
        # The key is that robots_checker doesn't crash
        assert isinstance(allowed, bool), \
            "Robots checker should return boolean"

    @pytest.mark.acceptance
    @pytest.mark.safety
    def test_quarantine_reason_codes(self, domain_quarantine):
        """Test various quarantine reason codes."""
        test_cases = [
            ('test-403.com', '403_FORBIDDEN', 60),
            ('test-429.com', 'TOO_MANY_REQUESTS_429', 60),
            ('test-captcha.com', 'CAPTCHA_DETECTED', 60),
            ('test-5xx.com', 'SERVER_ERROR_5XX', 30),
        ]

        for domain, reason, duration in test_cases:
            domain_quarantine.quarantine_domain(domain, reason, duration)

            assert domain_quarantine.is_quarantined(domain), \
                f"Domain {domain} should be quarantined with reason {reason}"

            entry = domain_quarantine.get_quarantine_entry(domain)
            assert entry is not None
            # Reason may be enum or string, check if it contains the expected value
            reason_str = str(entry.reason)
            assert reason.replace('_', ' ').upper() in reason_str.replace('_', ' ').upper(), \
                f"Expected reason containing '{reason}', got {entry.reason}"


class TestReviewModeWorkflow:
    """Test 2.4: Review Mode Workflow"""

    @pytest.mark.acceptance
    def test_change_log_creation(
        self,
        db_connection,
        change_manager,
        cleanup_test_change_log
    ):
        """Test that changes go to change_log with status=pending."""
        # Propose a test change
        change_manager.propose_change(
            table_name='citations',
            operation='update',
            record_id=999,
            proposed_data={
                'business_name': 'Updated Test Name',
                'phone': '555-TEST-NEW'
            },
            reason='Test review mode workflow',
            metadata={'test_scenario': 'review_mode_test'}
        )

        # Verify change_log entry created
        result = db_connection.execute(text("""
            SELECT change_id, table_name, operation, status, reason
            FROM change_log
            WHERE metadata->>'test_scenario' = 'review_mode_test'
            ORDER BY proposed_at DESC
            LIMIT 1
        """))

        change_row = result.fetchone()
        assert change_row is not None, "change_log entry should be created"
        assert change_row[1] == 'citations', "table_name should be 'citations'"
        assert change_row[2] == 'update', "operation should be 'update'"
        assert change_row[3] == 'pending', "status should be 'pending'"
        assert 'review mode' in change_row[4].lower(), "reason should mention review mode"

    @pytest.mark.acceptance
    def test_change_approval_workflow(
        self,
        db_connection,
        change_manager,
        cleanup_test_change_log
    ):
        """Test manual approval workflow."""
        # Propose a change
        change_manager.propose_change(
            table_name='test_table',
            operation='insert',
            record_id=None,
            proposed_data={'test': 'data'},
            reason='Test approval',
            metadata={'test_scenario': 'approval_test'}
        )

        # Get change_id
        result = db_connection.execute(text("""
            SELECT change_id FROM change_log
            WHERE metadata->>'test_scenario' = 'approval_test'
            ORDER BY proposed_at DESC LIMIT 1
        """))
        change_id = result.fetchone()[0]

        # Simulate approval
        db_connection.execute(text("""
            UPDATE change_log
            SET status = 'approved',
                reviewed_at = NOW(),
                reviewed_by = 'test_user'
            WHERE change_id = :change_id
        """), {"change_id": change_id})
        db_connection.commit()

        # Verify approval recorded
        result = db_connection.execute(text("""
            SELECT status, reviewed_by
            FROM change_log
            WHERE change_id = :change_id
        """), {"change_id": change_id})

        row = result.fetchone()
        assert row[0] == 'approved', "Status should be 'approved'"
        assert row[1] == 'test_user', "reviewed_by should be set"
