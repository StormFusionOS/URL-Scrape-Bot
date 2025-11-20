"""
SERP data extraction functions.

Extracts structured data from Google SERP pages:
- Organic search results (top 10)
- Featured snippets
- People Also Ask (PAA) questions
"""
import logging
from typing import Dict, List, Optional

from playwright.sync_api import Page

logger = logging.getLogger(__name__)


def extract_organic_results(page: Page, max_results: int = 10) -> List[Dict]:
    """
    Extract organic search results from SERP.

    Args:
        page: Playwright Page object with loaded SERP
        max_results: Maximum number of results to extract (default: 10)

    Returns:
        List of dicts with keys: position, url, title, description
    """
    results = []

    try:
        # Google organic results are in <div class="g"> or <div data-sokoban-container>
        # We use multiple selectors to handle different SERP layouts

        # Try main organic result container
        result_containers = page.query_selector_all('div.g')

        if not result_containers:
            # Fallback: try alternative selector
            result_containers = page.query_selector_all('div[data-sokoban-container]')

        if not result_containers:
            logger.warning("No organic result containers found on SERP")
            return results

        logger.info(f"Found {len(result_containers)} potential organic result containers")

        position = 1
        for container in result_containers:
            if position > max_results:
                break

            try:
                # Extract URL from <a> tag
                link_elem = container.query_selector('a')
                if not link_elem:
                    continue

                url = link_elem.get_attribute('href')
                if not url or not url.startswith('http'):
                    # Skip non-HTTP links (e.g., inline results, images)
                    continue

                # Extract title from <h3> tag
                title_elem = container.query_selector('h3')
                title = title_elem.inner_text() if title_elem else ''

                # Extract description from various possible selectors
                description = ''

                # Try standard description div
                desc_elem = container.query_selector('div[data-sncf="1"]')
                if desc_elem:
                    description = desc_elem.inner_text()

                # Fallback: try span with class VwiC3b (Google's snippet class)
                if not description:
                    desc_elem = container.query_selector('span.VwiC3b')
                    if desc_elem:
                        description = desc_elem.inner_text()

                # Fallback: try any div with style="-webkit-line-clamp"
                if not description:
                    desc_elem = container.query_selector('div[style*="-webkit-line-clamp"]')
                    if desc_elem:
                        description = desc_elem.inner_text()

                # Only add if we have at least URL and title
                if url and title:
                    results.append({
                        'position': position,
                        'url': url,
                        'title': title.strip(),
                        'description': description.strip() if description else ''
                    })
                    position += 1

            except Exception as e:
                logger.warning(f"Error extracting result at position {position}: {e}")
                continue

        logger.info(f"Extracted {len(results)} organic results")
        return results

    except Exception as e:
        logger.error(f"Error extracting organic results: {e}")
        return results


def extract_featured_snippet(page: Page) -> Optional[Dict]:
    """
    Extract featured snippet from SERP.

    Args:
        page: Playwright Page object with loaded SERP

    Returns:
        Dict with keys: type, content, url, title (or None if not found)
    """
    try:
        # Google featured snippets are typically in specific divs
        # Try multiple selectors as Google's markup changes

        # Selector 1: Standard featured snippet block
        snippet_container = page.query_selector('div.xpdopen')

        if not snippet_container:
            # Selector 2: Alternative featured snippet container
            snippet_container = page.query_selector('div[data-attrid*="kc:/"]')

        if not snippet_container:
            # Selector 3: Rich snippet container
            snippet_container = page.query_selector('div.kp-blk')

        if not snippet_container:
            logger.debug("No featured snippet found on SERP")
            return None

        # Extract content
        content = ''
        snippet_type = 'paragraph'  # Default type

        # Try to extract paragraph snippet
        paragraph_elem = snippet_container.query_selector('span[data-tts="answers"]')
        if paragraph_elem:
            content = paragraph_elem.inner_text()
            snippet_type = 'paragraph'

        # Try to extract list snippet
        if not content:
            list_elem = snippet_container.query_selector('ul, ol')
            if list_elem:
                content = list_elem.inner_text()
                snippet_type = 'list'

        # Try to extract table snippet
        if not content:
            table_elem = snippet_container.query_selector('table')
            if table_elem:
                content = table_elem.inner_text()
                snippet_type = 'table'

        # Fallback: get any text content
        if not content:
            content = snippet_container.inner_text()

        # Extract source URL and title
        url = ''
        title = ''

        link_elem = snippet_container.query_selector('a')
        if link_elem:
            url = link_elem.get_attribute('href') or ''

            # Extract title from cite or h3
            title_elem = snippet_container.query_selector('h3, cite')
            if title_elem:
                title = title_elem.inner_text()

        if content:
            snippet = {
                'type': snippet_type,
                'content': content.strip(),
                'url': url,
                'title': title.strip()
            }
            logger.info(f"Extracted featured snippet (type: {snippet_type})")
            return snippet

        return None

    except Exception as e:
        logger.error(f"Error extracting featured snippet: {e}")
        return None


def extract_paa_questions(
    page: Page,
    expand: bool = True,
    max_questions: int = 5
) -> List[Dict]:
    """
    Extract People Also Ask (PAA) questions from SERP.

    Args:
        page: Playwright Page object with loaded SERP
        expand: Whether to expand questions to get answers (default: True)
        max_questions: Maximum questions to extract (default: 5)

    Returns:
        List of dicts with keys: question, answer, url, position
    """
    questions = []

    try:
        # PAA section is typically in a specific div
        paa_containers = page.query_selector_all('div[data-q], div.related-question-pair')

        if not paa_containers:
            logger.debug("No PAA questions found on SERP")
            return questions

        logger.info(f"Found {len(paa_containers)} PAA question containers")

        for i, container in enumerate(paa_containers[:max_questions], 1):
            try:
                # Extract question text
                question_elem = container.query_selector('div[role="button"], span')
                if not question_elem:
                    continue

                question_text = question_elem.inner_text().strip()
                if not question_text:
                    continue

                answer = ''
                url = ''

                # Expand question to get answer if requested
                if expand:
                    try:
                        # Click to expand
                        question_elem.click()

                        # Wait for answer to load
                        page.wait_for_timeout(500)

                        # Extract answer
                        answer_elem = container.query_selector('div[data-attrid], div[data-tts="answers"]')
                        if answer_elem:
                            answer = answer_elem.inner_text().strip()

                        # Extract source URL
                        link_elem = container.query_selector('a[href^="http"]')
                        if link_elem:
                            url = link_elem.get_attribute('href') or ''

                    except Exception as e:
                        logger.warning(f"Error expanding PAA question {i}: {e}")

                questions.append({
                    'position': i,
                    'question': question_text,
                    'answer': answer,
                    'url': url
                })

            except Exception as e:
                logger.warning(f"Error extracting PAA question {i}: {e}")
                continue

        logger.info(f"Extracted {len(questions)} PAA questions")
        return questions

    except Exception as e:
        logger.error(f"Error extracting PAA questions: {e}")
        return questions


def extract_all_serp_data(
    page: Page,
    expand_paa: bool = True,
    max_paa: int = 5
) -> Dict:
    """
    Extract all SERP data in one pass.

    Args:
        page: Playwright Page object with loaded SERP
        expand_paa: Whether to expand PAA questions (default: True)
        max_paa: Maximum PAA questions to extract (default: 5)

    Returns:
        Dict with keys: organic_results, featured_snippet, paa_questions
    """
    logger.info("Extracting all SERP data...")

    data = {
        'organic_results': extract_organic_results(page),
        'featured_snippet': extract_featured_snippet(page),
        'paa_questions': extract_paa_questions(page, expand=expand_paa, max_questions=max_paa)
    }

    logger.info(
        f"SERP extraction complete: {len(data['organic_results'])} organic results, "
        f"{'1' if data['featured_snippet'] else '0'} featured snippet, "
        f"{len(data['paa_questions'])} PAA questions"
    )

    return data
