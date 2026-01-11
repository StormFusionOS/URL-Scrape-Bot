"""
Warmup Plan Executor

Executes warmup plans step-by-step with tier-specific behaviors.
Handles human-like interactions, failure recovery, and telemetry.

Key responsibilities:
- Navigate to URLs with proper timeouts
- Apply tier-specific behaviors (scroll, dwell, click)
- Handle cookie consent dialogs
- Record success/failure per step
- Determine session viability based on failures
"""

import asyncio
import random
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Any
from enum import Enum

from seo_intelligence.drivers.warmup_plan_factory import WarmupPlan, WarmupStep
from seo_intelligence.drivers.tiered_warmup_urls import WarmupTier

logger = logging.getLogger(__name__)


class StepResult(Enum):
    """Result of executing a warmup step."""
    SUCCESS = "success"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"
    ERROR = "error"
    SKIPPED = "skipped"


class SessionViability(Enum):
    """Overall session viability after warmup."""
    READY = "ready"
    DEGRADED = "degraded"  # Some failures but usable
    FAILED = "failed"      # Too many failures, recycle


@dataclass
class StepExecutionResult:
    """Result of executing a single warmup step."""
    step: WarmupStep
    result: StepResult
    duration_ms: int = 0
    error_message: Optional[str] = None
    page_title: Optional[str] = None
    cookies_set: int = 0

    @property
    def is_success(self) -> bool:
        return self.result == StepResult.SUCCESS


@dataclass
class WarmupExecutionResult:
    """Result of executing a complete warmup plan."""
    plan: WarmupPlan
    viability: SessionViability
    step_results: List[StepExecutionResult] = field(default_factory=list)
    total_duration_ms: int = 0
    cookies_total: int = 0

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.step_results if r.is_success)

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.step_results if not r.is_success)

    @property
    def success_rate(self) -> float:
        if not self.step_results:
            return 0.0
        return self.success_count / len(self.step_results)

    def __str__(self) -> str:
        return (
            f"WarmupResult: {self.viability.value}, "
            f"{self.success_count}/{len(self.step_results)} success, "
            f"{self.total_duration_ms}ms"
        )


class WarmupPlanExecutor:
    """
    Executes warmup plans with human-like behavior simulation.

    Usage:
        executor = WarmupPlanExecutor(page)
        result = await executor.execute(plan)
        if result.viability == SessionViability.READY:
            # Session is warmed and ready
    """

    # Timeouts per tier
    TIER_TIMEOUTS = {
        WarmupTier.S: 20000,  # 20s - institutional sites load fast
        WarmupTier.A: 25000,  # 25s - news sites can be slow
        WarmupTier.B: 30000,  # 30s - retail sites have heavy JS
        WarmupTier.C: 15000,  # 15s - fly-by only, don't wait
    }

    # Retry policy per tier
    TIER_RETRIES = {
        WarmupTier.S: 0,  # No retry, S failures are critical
        WarmupTier.A: 1,  # One retry
        WarmupTier.B: 0,  # No retry, continue
        WarmupTier.C: 0,  # No retry, these are optional
    }

    # Cookie consent button patterns
    COOKIE_SELECTORS = [
        "button[id*='accept']",
        "button[class*='accept']",
        "button[id*='cookie']",
        "button[class*='cookie']",
        "button[id*='consent']",
        "button[class*='consent']",
        "[data-testid*='accept']",
        "[data-testid*='cookie']",
        "button:has-text('Accept')",
        "button:has-text('Accept All')",
        "button:has-text('Accept Cookies')",
        "button:has-text('I Accept')",
        "button:has-text('Got it')",
        "button:has-text('OK')",
        "button:has-text('Agree')",
    ]

    def __init__(
        self,
        page: Any,  # Playwright Page
        on_step_complete: Optional[callable] = None,
        cookie_consent_probability: float = 0.7,
    ):
        """
        Initialize the executor.

        Args:
            page: Playwright Page instance
            on_step_complete: Optional callback after each step
            cookie_consent_probability: Chance to handle cookie dialogs
        """
        self.page = page
        self.on_step_complete = on_step_complete
        self.cookie_consent_probability = cookie_consent_probability

    async def execute(self, plan: WarmupPlan) -> WarmupExecutionResult:
        """
        Execute a complete warmup plan.

        Args:
            plan: The WarmupPlan to execute

        Returns:
            WarmupExecutionResult with viability assessment
        """
        start_time = time.time()
        result = WarmupExecutionResult(plan=plan, viability=SessionViability.READY)

        logger.info(f"Starting warmup execution: {plan}")

        tier_s_failed = False

        for i, step in enumerate(plan.steps):
            step_result = await self._execute_step(step, step_index=i)
            result.step_results.append(step_result)
            result.cookies_total += step_result.cookies_set

            # Track Tier S failures (critical)
            if step.tier == WarmupTier.S and not step_result.is_success:
                tier_s_failed = True
                logger.warning(f"Tier S failure: {step.url} - {step_result.error_message}")

            # Callback
            if self.on_step_complete:
                try:
                    await self.on_step_complete(step, step_result, i + 1, len(plan.steps))
                except Exception as e:
                    logger.warning(f"Step callback error: {e}")

            # Add small jitter between steps
            jitter = random.uniform(0.5, 2.0)
            await asyncio.sleep(jitter)

        # Calculate total duration
        result.total_duration_ms = int((time.time() - start_time) * 1000)

        # Determine viability
        result.viability = self._assess_viability(result, tier_s_failed)

        logger.info(f"Warmup execution complete: {result}")
        return result

    async def _execute_step(
        self,
        step: WarmupStep,
        step_index: int,
        retry_count: int = 0,
    ) -> StepExecutionResult:
        """Execute a single warmup step."""
        start_time = time.time()
        timeout = self.TIER_TIMEOUTS.get(step.tier, 25000)

        try:
            logger.debug(f"Executing step {step_index + 1}: {step}")

            # Navigate
            response = await self.page.goto(
                step.url,
                timeout=timeout,
                wait_until="domcontentloaded",
            )

            # Check for blocks/captchas
            if await self._detect_block():
                return StepExecutionResult(
                    step=step,
                    result=StepResult.BLOCKED,
                    duration_ms=int((time.time() - start_time) * 1000),
                    error_message="Detected block or CAPTCHA",
                )

            # Wait for network idle (with shorter timeout)
            try:
                await self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                # Network idle timeout is OK, continue
                pass

            # Handle cookie consent
            cookies_before = len(await self.page.context.cookies())
            if random.random() < self.cookie_consent_probability:
                await self._handle_cookie_consent()
            cookies_after = len(await self.page.context.cookies())

            # Apply tier-specific behavior
            await self._apply_behavior(step)

            # Get page info
            title = await self.page.title()

            duration_ms = int((time.time() - start_time) * 1000)

            return StepExecutionResult(
                step=step,
                result=StepResult.SUCCESS,
                duration_ms=duration_ms,
                page_title=title,
                cookies_set=cookies_after - cookies_before,
            )

        except asyncio.TimeoutError:
            duration_ms = int((time.time() - start_time) * 1000)

            # Retry logic
            max_retries = self.TIER_RETRIES.get(step.tier, 0)
            if retry_count < max_retries:
                logger.info(f"Retrying step {step_index + 1} ({retry_count + 1}/{max_retries})")
                await asyncio.sleep(2)  # Brief pause before retry
                return await self._execute_step(step, step_index, retry_count + 1)

            return StepExecutionResult(
                step=step,
                result=StepResult.TIMEOUT,
                duration_ms=duration_ms,
                error_message=f"Timeout after {timeout}ms",
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)[:200]

            logger.warning(f"Step {step_index + 1} error: {error_msg}")

            return StepExecutionResult(
                step=step,
                result=StepResult.ERROR,
                duration_ms=duration_ms,
                error_message=error_msg,
            )

    async def _apply_behavior(self, step: WarmupStep) -> None:
        """Apply tier-specific human-like behavior."""
        try:
            # Dwell time (wait and "read")
            await asyncio.sleep(step.dwell_time)

            # Scrolling
            if step.should_scroll and step.scroll_depth > 0:
                await self._perform_scroll(step.scroll_depth)

            # Clicking (internal navigation)
            if step.should_click:
                await self._perform_click()

        except Exception as e:
            logger.debug(f"Behavior error (non-critical): {e}")

    async def _perform_scroll(self, target_depth: float) -> None:
        """Perform human-like scrolling."""
        try:
            # Get page height
            page_height = await self.page.evaluate("document.body.scrollHeight")
            viewport_height = await self.page.evaluate("window.innerHeight")

            target_scroll = int(page_height * target_depth)

            # Scroll in chunks with variable speed
            current_pos = 0
            while current_pos < target_scroll:
                # Random scroll increment (100-400px)
                increment = random.randint(100, 400)
                current_pos = min(current_pos + increment, target_scroll)

                await self.page.evaluate(f"window.scrollTo(0, {current_pos})")

                # Random pause between scrolls
                pause = random.uniform(0.3, 1.0)
                await asyncio.sleep(pause)

            # Sometimes scroll back up slightly
            if random.random() < 0.3:
                scroll_back = random.randint(50, 200)
                await self.page.evaluate(f"window.scrollBy(0, -{scroll_back})")

        except Exception as e:
            logger.debug(f"Scroll error: {e}")

    async def _perform_click(self) -> None:
        """Perform a click on an internal link."""
        try:
            # Find clickable internal links
            links = await self.page.query_selector_all("a[href^='/']")
            if not links:
                links = await self.page.query_selector_all("a:not([href^='http'])")

            if links:
                # Filter to visible links
                visible_links = []
                for link in links[:20]:  # Check first 20
                    try:
                        if await link.is_visible():
                            visible_links.append(link)
                    except Exception:
                        pass

                if visible_links:
                    # Click random visible link
                    link = random.choice(visible_links)
                    await link.click(timeout=3000)

                    # Wait briefly for navigation
                    await asyncio.sleep(2)

                    # Go back
                    await self.page.go_back(timeout=5000)

        except Exception as e:
            logger.debug(f"Click error: {e}")

    async def _handle_cookie_consent(self) -> None:
        """Try to dismiss cookie consent dialogs."""
        try:
            for selector in self.COOKIE_SELECTORS:
                try:
                    button = await self.page.query_selector(selector)
                    if button and await button.is_visible():
                        await button.click(timeout=2000)
                        await asyncio.sleep(0.5)
                        logger.debug(f"Clicked cookie consent: {selector}")
                        return
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Cookie consent handling error: {e}")

    async def _detect_block(self) -> bool:
        """Detect if page shows block/CAPTCHA."""
        try:
            page_text = await self.page.inner_text("body")
            page_text_lower = page_text.lower()

            block_indicators = [
                "access denied",
                "blocked",
                "captcha",
                "robot",
                "unusual traffic",
                "verify you are human",
                "please complete the security check",
                "enable javascript",
                "browser check",
            ]

            for indicator in block_indicators:
                if indicator in page_text_lower:
                    return True

            # Check for reCAPTCHA iframe
            captcha_frame = await self.page.query_selector("iframe[src*='recaptcha']")
            if captcha_frame:
                return True

            return False

        except Exception:
            return False

    def _assess_viability(
        self,
        result: WarmupExecutionResult,
        tier_s_failed: bool,
    ) -> SessionViability:
        """Assess overall session viability based on warmup results."""
        # Tier S failure is always critical
        if tier_s_failed:
            return SessionViability.FAILED

        # Calculate success rate
        success_rate = result.success_rate

        # Count critical vs non-critical failures
        tier_a_failures = sum(
            1 for r in result.step_results
            if r.step.tier == WarmupTier.A and not r.is_success
        )

        # Thresholds
        if success_rate >= 0.8:
            return SessionViability.READY
        elif success_rate >= 0.5:
            # Degraded if we had some success
            if tier_a_failures <= 1:
                return SessionViability.DEGRADED
            else:
                return SessionViability.FAILED
        else:
            return SessionViability.FAILED


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def execute_warmup_plan(
    page: Any,
    plan: WarmupPlan,
    on_step_complete: Optional[callable] = None,
) -> WarmupExecutionResult:
    """
    Convenience function to execute a warmup plan.

    Args:
        page: Playwright Page instance
        plan: WarmupPlan to execute
        on_step_complete: Optional callback

    Returns:
        WarmupExecutionResult
    """
    executor = WarmupPlanExecutor(page, on_step_complete=on_step_complete)
    return await executor.execute(plan)


async def quick_warmup(
    page: Any,
    url_count: int = 3,
) -> bool:
    """
    Perform a quick warmup with minimal URLs (for testing).

    Args:
        page: Playwright Page
        url_count: Number of URLs to visit

    Returns:
        True if warmup successful
    """
    from seo_intelligence.drivers.warmup_plan_factory import create_warmup_plan

    # Create plan with adjusted parameters
    plan = create_warmup_plan()

    # Limit steps
    plan.steps = plan.steps[:url_count]

    executor = WarmupPlanExecutor(page)
    result = await executor.execute(plan)

    return result.viability != SessionViability.FAILED
