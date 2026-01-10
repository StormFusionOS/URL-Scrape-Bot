"""
Example: Qdrant Embedding Pipeline Workflow

This script demonstrates the complete embedding workflow for the SEO Intelligence system.
It shows how to:
1. Initialize Qdrant collections
2. Crawl competitor pages with embeddings enabled
3. Scrape SERP results with snippet embeddings
4. Perform semantic search on competitor content
5. Check embedding status

Per SCRAPER BOT.pdf specification.

Usage:
    python example_embedding_workflow.py

Prerequisites:
    - Qdrant running (docker run -p 6333:6333 qdrant/qdrant)
    - DATABASE_URL set in .env
    - Dependencies installed (pip install -r requirements.txt)
"""

import os
from dotenv import load_dotenv

# Load environment
load_dotenv()


def step1_initialize_qdrant():
    """Step 1: Initialize Qdrant collections"""
    print("\n" + "=" * 70)
    print("STEP 1: Initialize Qdrant Collections")
    print("=" * 70)

    from seo_intelligence.services import get_qdrant_manager

    try:
        qdrant = get_qdrant_manager()

        # Check health
        if not qdrant.health_check():
            print("❌ ERROR: Could not connect to Qdrant")
            print("   Make sure Qdrant is running:")
            print("   docker run -p 6333:6333 qdrant/qdrant")
            return False

        print("✓ Connected to Qdrant")

        # Initialize collections
        qdrant.initialize_collections()

        # Show stats
        for collection in [qdrant.COMPETITOR_PAGES, qdrant.SERP_SNIPPETS]:
            stats = qdrant.get_collection_stats(collection)
            print(f"\n  Collection: {collection}")
            print(f"  - Vectors: {stats['vectors_count']}")
            print(f"  - Status: {stats['status']}")

        print("\n✓ Collections initialized successfully")
        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


def step2_crawl_with_embeddings():
    """Step 2: Crawl competitor pages with embeddings enabled"""
    print("\n" + "=" * 70)
    print("STEP 2: Crawl Competitor with Embeddings")
    print("=" * 70)

    from seo_intelligence.scrapers import get_competitor_crawler

    try:
        # Initialize crawler with embeddings enabled
        crawler = get_competitor_crawler(
            headless=True,
            use_proxy=False,  # Disable proxy for testing
            enable_embeddings=True  # Enable embedding generation
        )

        # Example competitor (replace with your test domain)
        test_domain = "example.com"
        print(f"\nCrawling {test_domain}...")
        print("Note: This is a test. Replace 'example.com' with your actual competitor domain.")

        # For demonstration, we'll show the configuration only
        print("\n✓ Crawler initialized with:")
        print(f"  - Embeddings: {crawler.enable_embeddings}")
        print(f"  - Model: {crawler.embedder.embedder.model_name if crawler.enable_embeddings else 'N/A'}")
        print(f"  - Dimension: {crawler.embedder.embedder.dimension if crawler.enable_embeddings else 'N/A'}")

        # Uncomment to actually crawl:
        # result = crawler.crawl_competitor(
        #     domain=test_domain,
        #     name="Test Competitor",
        #     location="Austin, TX"
        # )
        #
        # if result:
        #     print(f"\n✓ Crawled {result['pages_crawled']} pages")
        #     print(f"  - Total words: {result['total_words']}")

        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


def step3_scrape_serp_with_embeddings():
    """Step 3: Scrape SERP with snippet embeddings"""
    print("\n" + "=" * 70)
    print("STEP 3: Scrape SERP with Snippet Embeddings")
    print("=" * 70)

    from seo_intelligence.scrapers import get_serp_scraper

    try:
        # Initialize SERP scraper with embeddings enabled
        scraper = get_serp_scraper(
            headless=True,
            use_proxy=False,  # Disable proxy for testing
            enable_embeddings=True  # Enable snippet embedding
        )

        # Example query
        test_query = "pressure washing services"
        print(f"\nSearching for: '{test_query}'")
        print("Note: This is a test. Actual SERP scraping should be done with caution.")

        # Show configuration
        print("\n✓ SERP scraper initialized with:")
        print(f"  - Embeddings: {scraper.enable_embeddings}")
        print(f"  - Model: {scraper.embedder.embedder.model_name if scraper.enable_embeddings else 'N/A'}")

        # Uncomment to actually scrape:
        # snapshot = scraper.scrape_query(
        #     query=test_query,
        #     location="Austin, TX"
        # )
        #
        # if snapshot:
        #     print(f"\n✓ Found {len(snapshot.results)} results")
        #     print(f"  - Snippets embedded: {len([r for r in snapshot.results if r.description])}")

        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


def step4_semantic_search():
    """Step 4: Perform semantic search on competitor content"""
    print("\n" + "=" * 70)
    print("STEP 4: Semantic Search Demo")
    print("=" * 70)

    from seo_intelligence.services import get_content_embedder, get_qdrant_manager

    try:
        embedder = get_content_embedder()
        qdrant = get_qdrant_manager()

        # Example search query
        search_query = "pressure washing and power washing services"
        print(f"\nSearching for: '{search_query}'")

        # Embed the query
        query_vector = embedder.embed_single(search_query)
        print(f"✓ Query embedded ({len(query_vector)} dimensions)")

        # Search similar pages
        results = qdrant.search_similar_pages(
            query_vector=query_vector,
            limit=5
        )

        if results:
            print(f"\n✓ Found {len(results)} similar pages:\n")
            for i, result in enumerate(results, 1):
                print(f"{i}. {result['title']}")
                print(f"   URL: {result['url']}")
                print(f"   Type: {result['page_type']}")
                print(f"   Score: {result['score']:.3f}")
                print()
        else:
            print("\n⚠ No results found. Make sure you've crawled competitors with embeddings enabled.")

        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


def step5_check_status():
    """Step 5: Check embedding status and statistics"""
    print("\n" + "=" * 70)
    print("STEP 5: Embedding Status")
    print("=" * 70)

    from seo_intelligence.services import get_content_embedder, get_qdrant_manager
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    try:
        embedder = get_content_embedder()
        qdrant = get_qdrant_manager()

        # Show configuration
        print("\nConfiguration:")
        info = embedder.get_info()
        print(f"  Model: {info['model_name']}")
        print(f"  Version: {info['embedding_version']}")
        print(f"  Dimension: {info['dimension']}")
        print(f"  Chunk Size: {info['chunk_size']} tokens")

        # Qdrant status
        print("\nQdrant Status:")
        if qdrant.health_check():
            print(f"  ✓ Connected to {qdrant.host}:{qdrant.port}")

            for collection in [qdrant.COMPETITOR_PAGES, qdrant.SERP_SNIPPETS]:
                stats = qdrant.get_collection_stats(collection)
                print(f"\n  {collection}:")
                print(f"    Vectors: {stats['vectors_count']}")
                print(f"    Status: {stats['status']}")
        else:
            print("  ❌ Not connected")

        # Database stats
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            engine = create_engine(database_url, echo=False)

            with Session(engine) as session:
                # Competitor pages
                result = session.execute(
                    text("""
                        SELECT
                            COUNT(*) as total,
                            COUNT(embedding_version) as embedded,
                            COUNT(CASE WHEN embedding_version = :version THEN 1 END) as current_version
                        FROM competitor_pages
                    """),
                    {"version": os.getenv("EMBEDDING_VERSION", "v1.0")}
                ).fetchone()

                print("\nDatabase (competitor_pages):")
                print(f"  Total pages: {result[0]}")
                print(f"  Embedded: {result[1]}")
                print(f"  Current version: {result[2]}")

                # SERP results
                result = session.execute(
                    text("""
                        SELECT
                            COUNT(*) as total,
                            COUNT(embedding_version) as embedded
                        FROM serp_results
                    """)
                ).fetchone()

                print("\nDatabase (serp_results):")
                print(f"  Total results: {result[0]}")
                print(f"  Embedded snippets: {result[1]}")
        else:
            print("\n⚠ DATABASE_URL not set")

        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


def main():
    """Run the complete embedding workflow demonstration"""
    print("\n" + "=" * 70)
    print("SEO Intelligence: Qdrant Embedding Pipeline Demo")
    print("=" * 70)
    print("\nThis script demonstrates the complete embedding workflow.")
    print("Per SCRAPER BOT.pdf specification.\n")

    # Run all steps
    steps = [
        ("Initialize Qdrant", step1_initialize_qdrant),
        ("Crawl with Embeddings", step2_crawl_with_embeddings),
        ("SERP with Embeddings", step3_scrape_serp_with_embeddings),
        ("Semantic Search", step4_semantic_search),
        ("Check Status", step5_check_status),
    ]

    results = []
    for step_name, step_func in steps:
        try:
            success = step_func()
            results.append((step_name, success))
        except KeyboardInterrupt:
            print("\n\n⚠ Interrupted by user")
            break
        except Exception as e:
            print(f"\n❌ ERROR in {step_name}: {e}")
            results.append((step_name, False))

    # Summary
    print("\n" + "=" * 70)
    print("WORKFLOW SUMMARY")
    print("=" * 70)
    for step_name, success in results:
        status = "✓" if success else "❌"
        print(f"{status} {step_name}")

    print("\n" + "=" * 70)
    print("NEXT STEPS")
    print("=" * 70)
    print("\n1. Use CLI commands:")
    print("   python -m seo_intelligence embed --initialize")
    print("   python -m seo_intelligence embed --status")
    print("   python -m seo_intelligence embed --search --query 'your query'")
    print("\n2. Crawl competitors with embeddings:")
    print("   python -m seo_intelligence competitor --domain example.com")
    print("\n3. Run SERP scraper with embeddings:")
    print("   python -m seo_intelligence serp --query 'your keywords'")
    print("\n4. For quarterly re-embedding:")
    print("   - Update EMBEDDING_VERSION in .env (e.g., v2.0)")
    print("   - Re-crawl competitors to generate new embeddings")
    print("\nFor more information, see:")
    print("  - docs/SCRAPER_BOT.pdf")
    print("  - seo_intelligence/services/embedding_service.py")
    print("  - seo_intelligence/services/qdrant_manager.py")
    print()


if __name__ == "__main__":
    main()
