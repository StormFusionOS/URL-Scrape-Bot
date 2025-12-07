#!/usr/bin/env python3
"""
Claude API Client for verification auto-tuning.

Handles all interactions with Anthropic Claude API including:
- Rate limiting (50 req/min for Pro accounts)
- Prompt caching for cost optimization
- Retry logic with exponential backoff
- Token tracking and cost estimation
- Error categorization and handling
"""

import os
import time
import json
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import asyncio

try:
    from anthropic import Anthropic, AnthropicError, RateLimitError, APIError
except ImportError:
    raise ImportError("anthropic package not installed. Run: pip install anthropic>=0.39.0")

from verification.config_verifier import (
    CLAUDE_MODEL,
    CLAUDE_MAX_TOKENS,
    CLAUDE_TEMPERATURE,
    CLAUDE_MAX_RETRIES,
)


logger = logging.getLogger(__name__)


# ==============================================================================
# DATA STRUCTURES
# ==============================================================================

@dataclass
class ClaudeReviewResult:
    """Result from Claude API review."""
    # Decision
    decision: str  # approve, deny, unclear
    confidence: float
    reasoning: str
    is_provider: bool

    # Extracted data
    primary_services: List[str]
    identified_red_flags: List[str]

    # API metrics
    api_latency_ms: int
    tokens_input: int
    tokens_output: int
    cached_tokens: int
    cost_estimate: float

    # Metadata
    raw_response: dict
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class RateLimitState:
    """Track rate limit state for Claude API."""
    requests_this_minute: int = 0
    minute_bucket: datetime = None
    tokens_this_hour: int = 0
    hour_bucket: datetime = None

    def reset_if_needed(self):
        """Reset counters if we've moved to a new time bucket."""
        now = datetime.now()

        # Reset minute bucket
        current_minute = now.replace(second=0, microsecond=0)
        if self.minute_bucket is None or current_minute > self.minute_bucket:
            self.minute_bucket = current_minute
            self.requests_this_minute = 0

        # Reset hour bucket
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        if self.hour_bucket is None or current_hour > self.hour_bucket:
            self.hour_bucket = current_hour
            self.tokens_this_hour = 0


# ==============================================================================
# RATE LIMITER
# ==============================================================================

class RateLimiter:
    """Rate limiter for Claude API (50 requests/minute for Pro)."""

    def __init__(self, requests_per_minute: int = 50):
        self.requests_per_minute = requests_per_minute
        self.min_delay_seconds = 60.0 / requests_per_minute  # 1.2s for 50 req/min
        self.last_request_time: Optional[float] = None
        self.state = RateLimitState()

    async def acquire(self):
        """Wait if necessary to respect rate limits."""
        self.state.reset_if_needed()

        # Check if we've hit the minute limit
        if self.state.requests_this_minute >= self.requests_per_minute:
            # Wait until next minute
            now = datetime.now()
            next_minute = (self.state.minute_bucket + timedelta(minutes=1))
            wait_seconds = (next_minute - now).total_seconds()
            if wait_seconds > 0:
                logger.warning(f"Rate limit reached, waiting {wait_seconds:.1f}s")
                await asyncio.sleep(wait_seconds)
                self.state.reset_if_needed()

        # Enforce minimum delay between requests
        if self.last_request_time is not None:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.min_delay_seconds:
                wait_time = self.min_delay_seconds - elapsed
                await asyncio.sleep(wait_time)

        self.last_request_time = time.time()
        self.state.requests_this_minute += 1


# ==============================================================================
# COST CALCULATOR
# ==============================================================================

class CostCalculator:
    """Calculate API costs for Claude 3.5 Sonnet."""

    # Pricing per million tokens (as of Dec 2025)
    COST_INPUT = 3.00  # $3 per 1M input tokens
    COST_OUTPUT = 15.00  # $15 per 1M output tokens
    COST_CACHE_WRITE = 3.75  # $3.75 per 1M cache write tokens
    COST_CACHE_READ = 0.30  # $0.30 per 1M cache read tokens

    @classmethod
    def calculate(
        cls,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        cache_creation_tokens: int = 0
    ) -> float:
        """
        Calculate estimated cost.

        Args:
            input_tokens: Non-cached input tokens
            output_tokens: Output tokens generated
            cached_tokens: Tokens served from cache
            cache_creation_tokens: Tokens written to cache (first time)

        Returns:
            Cost in USD
        """
        cost = 0.0

        # Input tokens (not cached)
        cost += (input_tokens / 1_000_000) * cls.COST_INPUT

        # Output tokens
        cost += (output_tokens / 1_000_000) * cls.COST_OUTPUT

        # Cache write (first time caching)
        cost += (cache_creation_tokens / 1_000_000) * cls.COST_CACHE_WRITE

        # Cache read (served from cache)
        cost += (cached_tokens / 1_000_000) * cls.COST_CACHE_READ

        return cost


# ==============================================================================
# CLAUDE API CLIENT
# ==============================================================================

class ClaudeAPIClient:
    """
    Production Claude API client with caching, rate limiting, and retry logic.

    Features:
    - Prompt caching (60% cost reduction)
    - Rate limiting (50 req/min for Pro)
    - Exponential backoff retry
    - Token tracking and cost estimation
    - Comprehensive error handling
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Claude API client.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment")

        self.client = Anthropic(api_key=self.api_key)
        self.rate_limiter = RateLimiter(requests_per_minute=50)
        self.model = CLAUDE_MODEL
        self.max_tokens = CLAUDE_MAX_TOKENS
        self.temperature = CLAUDE_TEMPERATURE

        logger.info(f"ClaudeAPIClient initialized (model={self.model})")

    async def review_company(
        self,
        company_data: dict,
        system_prompt: str,
        few_shot_examples: List[dict],
        company_context: str,
        prompt_version: str
    ) -> ClaudeReviewResult:
        """
        Send company to Claude for review.

        Args:
            company_data: Company metadata (ID, name, URL, etc.)
            system_prompt: System instructions (cached)
            few_shot_examples: Example reviews (cached)
            company_context: Specific company data (not cached)
            prompt_version: Version of prompt used

        Returns:
            ClaudeReviewResult with decision and metadata
        """
        start_time = time.time()

        # Build messages with caching
        messages = self._build_messages(
            system_prompt=system_prompt,
            few_shot_examples=few_shot_examples,
            company_context=company_context
        )

        # Rate limit
        await self.rate_limiter.acquire()

        # Call API with retry logic
        for attempt in range(CLAUDE_MAX_RETRIES):
            try:
                response = await self._call_api(messages, system_prompt)

                # Parse response
                result = self._parse_response(
                    response=response,
                    company_data=company_data,
                    start_time=start_time,
                    prompt_version=prompt_version
                )

                logger.info(
                    f"✓ Claude review: company_id={company_data.get('company_id')} "
                    f"decision={result.decision} confidence={result.confidence:.2f} "
                    f"cost=${result.cost_estimate:.4f}"
                )

                return result

            except RateLimitError as e:
                logger.warning(f"Rate limit hit (attempt {attempt + 1}/{CLAUDE_MAX_RETRIES})")
                if attempt < CLAUDE_MAX_RETRIES - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    await asyncio.sleep(wait_time)
                else:
                    return self._error_result(
                        company_data, start_time, f"Rate limit exceeded: {e}"
                    )

            except APIError as e:
                logger.error(f"API error (attempt {attempt + 1}/{CLAUDE_MAX_RETRIES}): {e}")
                if attempt < CLAUDE_MAX_RETRIES - 1:
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)
                else:
                    return self._error_result(
                        company_data, start_time, f"API error: {e}"
                    )

            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                return self._error_result(
                    company_data, start_time, f"Unexpected error: {e}"
                )

        # Should not reach here
        return self._error_result(
            company_data, start_time, "Max retries exceeded"
        )

    def _build_messages(
        self,
        system_prompt: str,
        few_shot_examples: List[dict],
        company_context: str
    ) -> List[dict]:
        """
        Build messages with prompt caching.

        Caching strategy:
        - System prompt: Cached (static, updated weekly)
        - Few-shot examples: Cached (static, updated weekly)
        - Company context: NOT cached (unique per company)
        """
        messages = []

        # System message with few-shot examples (cached)
        if few_shot_examples:
            examples_text = self._format_examples(few_shot_examples)
            full_system = f"{system_prompt}\n\n## Few-Shot Examples\n\n{examples_text}"
        else:
            full_system = system_prompt

        # User message: Company to review (not cached)
        messages.append({
            "role": "user",
            "content": f"## Company to Review\n\n{company_context}"
        })

        return messages, full_system

    def _format_examples(self, examples: List[dict]) -> str:
        """Format few-shot examples for prompt."""
        formatted = []
        for i, ex in enumerate(examples, 1):
            formatted.append(f"### Example {i}")
            formatted.append(f"**Input:**\n{json.dumps(ex.get('input', {}), indent=2)}")
            formatted.append(f"**Output:**\n{json.dumps(ex.get('output', {}), indent=2)}")
            formatted.append("")
        return "\n".join(formatted)

    async def _call_api(self, messages_and_system: Tuple, system_prompt: str) -> dict:
        """
        Call Claude API with caching.

        Uses prompt caching for system instructions and few-shot examples.
        """
        messages, full_system = messages_and_system

        # Use sync client (Anthropic SDK handles async internally)
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=[
                {
                    "type": "text",
                    "text": full_system,
                    "cache_control": {"type": "ephemeral"}  # Cache system prompt
                }
            ],
            messages=messages
        )

        return response

    def _parse_response(
        self,
        response,
        company_data: dict,
        start_time: float,
        prompt_version: str
    ) -> ClaudeReviewResult:
        """Parse Claude API response into ClaudeReviewResult."""

        # Extract text from response
        content_blocks = response.content
        if not content_blocks:
            raise ValueError("Empty response from Claude")

        text = content_blocks[0].text

        # Parse JSON response
        try:
            # Handle potential markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {text[:200]}")
            raise ValueError(f"Invalid JSON response: {e}")

        # Extract usage stats
        usage = response.usage
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        cached_tokens = getattr(usage, 'cache_read_input_tokens', 0)
        cache_creation_tokens = getattr(usage, 'cache_creation_input_tokens', 0)

        # Calculate cost
        cost = CostCalculator.calculate(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens
        )

        # Calculate latency
        latency_ms = int((time.time() - start_time) * 1000)

        # Build result
        return ClaudeReviewResult(
            decision=parsed.get('decision', 'unclear'),
            confidence=float(parsed.get('confidence', 0.5)),
            reasoning=parsed.get('reasoning', ''),
            is_provider=bool(parsed.get('is_provider', False)),
            primary_services=parsed.get('primary_services', []),
            identified_red_flags=parsed.get('red_flags', []),
            api_latency_ms=latency_ms,
            tokens_input=input_tokens,
            tokens_output=output_tokens,
            cached_tokens=cached_tokens,
            cost_estimate=cost,
            raw_response={
                'content': text,
                'usage': {
                    'input_tokens': input_tokens,
                    'output_tokens': output_tokens,
                    'cached_tokens': cached_tokens,
                    'cache_creation_tokens': cache_creation_tokens
                },
                'model': response.model,
                'stop_reason': response.stop_reason
            },
            success=True
        )

    def _error_result(
        self,
        company_data: dict,
        start_time: float,
        error_message: str
    ) -> ClaudeReviewResult:
        """Create error result."""
        latency_ms = int((time.time() - start_time) * 1000)

        return ClaudeReviewResult(
            decision='unclear',
            confidence=0.0,
            reasoning=f"Error: {error_message}",
            is_provider=False,
            primary_services=[],
            identified_red_flags=[],
            api_latency_ms=latency_ms,
            tokens_input=0,
            tokens_output=0,
            cached_tokens=0,
            cost_estimate=0.0,
            raw_response={'error': error_message},
            success=False,
            error_message=error_message
        )


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def test_api_connection():
    """Test Claude API connection."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not found in environment")
        return False

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=50,
            messages=[{"role": "user", "content": "Say 'API connection successful' and nothing else."}]
        )
        print(f"✓ API connection successful: {response.content[0].text}")
        return True
    except Exception as e:
        print(f"✗ API connection failed: {e}")
        return False


if __name__ == "__main__":
    import asyncio

    # Test API connection
    print("Testing Claude API connection...")
    test_api_connection()
