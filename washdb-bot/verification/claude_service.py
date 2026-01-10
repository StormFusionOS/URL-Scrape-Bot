#!/usr/bin/env python3
"""
Claude Auto-Tuning Service Daemon.

Long-running service that:
- Processes companies from claude_review_queue
- Calls Claude API for borderline cases
- Auto-applies decisions (audit mode)
- Maintains comprehensive audit trail
- Handles errors with retry logic
- Respects rate limits and cost budgets

Architecture:
- Main processing loop (async)
- Unix socket server for status/control
- Comprehensive error handling
- Graceful shutdown

Usage:
    python verification/claude_service.py
"""

import os
import sys
import signal
import socket
import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from db.database_manager import get_db_manager
from verification.claude_api_client import ClaudeAPIClient, ClaudeReviewResult
from verification.claude_prompt_manager import PromptManager
from verification.config_verifier import (
    CLAUDE_SOCKET_PATH,
    CLAUDE_QUEUE_BATCH_SIZE,
    CLAUDE_PROCESS_DELAY_SECONDS,
    CLAUDE_CONFIDENCE_THRESHOLD,
    CLAUDE_MAX_COST_PER_DAY,
    CLAUDE_MAX_REVIEWS_PER_DAY,
    CLAUDE_REVIEW_SCORE_MIN,
    CLAUDE_REVIEW_SCORE_MAX
)


# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/claude_service.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# ==============================================================================
# SERVICE STATISTICS
# ==============================================================================

class ServiceStats:
    """Track service statistics."""

    def __init__(self):
        self.reviews_processed = 0
        self.approvals = 0
        self.denials = 0
        self.unclear = 0
        self.errors = 0
        self.total_cost = 0.0
        self.total_latency_ms = 0
        self.cache_hits = 0
        self.start_time = datetime.now()

    def record_success(self, result: ClaudeReviewResult):
        """Record successful review."""
        self.reviews_processed += 1

        if result.decision == 'approve':
            self.approvals += 1
        elif result.decision == 'deny':
            self.denials += 1
        else:
            self.unclear += 1

        self.total_cost += result.cost_estimate
        self.total_latency_ms += result.api_latency_ms

        if result.cached_tokens > 0:
            self.cache_hits += 1

    def record_error(self):
        """Record error."""
        self.errors += 1

    def get_summary(self) -> dict:
        """Get summary statistics."""
        uptime = (datetime.now() - self.start_time).total_seconds()

        return {
            'uptime_seconds': int(uptime),
            'reviews_processed': self.reviews_processed,
            'approvals': self.approvals,
            'denials': self.denials,
            'unclear': self.unclear,
            'errors': self.errors,
            'total_cost': round(self.total_cost, 4),
            'avg_latency_ms': int(self.total_latency_ms / max(self.reviews_processed, 1)),
            'cache_hit_rate': round(self.cache_hits / max(self.reviews_processed, 1), 2),
            'reviews_per_hour': round(self.reviews_processed / (uptime / 3600), 1)
        }


# ==============================================================================
# CLAUDE SERVICE
# ==============================================================================

class ClaudeService:
    """
    Production service for Claude-powered verification reviews.

    Continuously processes companies from queue, manages rate limits,
    handles errors with retry logic, and maintains audit trail.
    """

    def __init__(self):
        """Initialize Claude service."""
        self.db_manager = get_db_manager()
        self.api_client = ClaudeAPIClient()
        self.prompt_manager = PromptManager(db_manager=self.db_manager)
        self.stats = ServiceStats()

        self.running = False
        self.paused = False

        # Safety limits
        self.daily_cost_limit = CLAUDE_MAX_COST_PER_DAY
        self.daily_review_limit = CLAUDE_MAX_REVIEWS_PER_DAY

        logger.info("ClaudeService initialized")

    async def start(self):
        """Start service (main entry point)."""
        self.running = True
        logger.info("=" * 70)
        logger.info("CLAUDE AUTO-TUNING SERVICE STARTED")
        logger.info("=" * 70)

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Start Unix socket server (non-blocking)
        asyncio.create_task(self._run_socket_server())

        # Start main processing loop
        try:
            await self._process_queue_loop()
        except Exception as e:
            logger.error(f"Fatal error in processing loop: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.shutdown()

    async def _process_queue_loop(self):
        """Main processing loop."""
        empty_queue_count = 0

        while self.running:
            try:
                # Check if paused
                if self.paused:
                    logger.info("Service paused, waiting...")
                    await asyncio.sleep(10)
                    continue

                # Check safety limits
                if not await self._check_safety_limits():
                    logger.warning("Safety limits reached, pausing for 1 hour...")
                    await asyncio.sleep(3600)
                    continue

                # Get next batch from queue
                companies = await self._get_next_batch(CLAUDE_QUEUE_BATCH_SIZE)

                if not companies:
                    empty_queue_count += 1
                    backoff = min(60 * empty_queue_count, 300)  # Max 5 min backoff
                    logger.info(f"Queue empty, waiting {backoff}s...")
                    await asyncio.sleep(backoff)
                    continue

                # Reset empty queue counter
                empty_queue_count = 0

                # Process batch
                for company in companies:
                    if not self.running:
                        break

                    try:
                        await self._process_company(company)
                    except Exception as e:
                        logger.error(f"Error processing company {company.get('id')}: {e}")
                        await self._handle_error(company, str(e))

                    # Delay between requests (rate limiting)
                    await asyncio.sleep(CLAUDE_PROCESS_DELAY_SECONDS)

            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
                await asyncio.sleep(10)

    async def _get_next_batch(self, limit: int) -> List[dict]:
        """
        Get next batch of companies from queue.

        Priority order: Lowest priority number first.
        """
        query = """
            UPDATE claude_review_queue
            SET status = 'processing',
                processing_started_at = NOW()
            WHERE id IN (
                SELECT id FROM claude_review_queue
                WHERE status = 'pending'
                ORDER BY priority ASC, queued_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, company_id, priority, score
        """

        with self.db_manager.get_session() as session:
            result = session.execute(text(query), {'limit': limit})
            queue_rows = result.fetchall()
            # commit handled by context manager

        if not queue_rows:
            return []

        # Fetch company data
        company_ids = [row[1] for row in queue_rows]
        company_query = """
            SELECT id, name, website, parse_metadata
            FROM companies
            WHERE id = ANY(:ids)
        """

        with self.db_manager.get_session() as session:
            result = session.execute(text(company_query), {'ids': company_ids})
            company_rows = result.fetchall()

        # Build company dicts
        companies = []
        for row in company_rows:
            company_id, name, website, metadata = row
            companies.append({
                'id': company_id,
                'name': name,
                'website': website,
                'parse_metadata': metadata
            })

        logger.info(f"Retrieved {len(companies)} companies from queue")
        return companies

    async def _process_company(self, company: dict):
        """Process a single company."""
        company_id = company.get('id')
        logger.info(f"Processing company: {company_id} ({company.get('name')})")

        # Build prompt
        prompt_data = self.prompt_manager.build_prompt(company)

        # Call Claude API
        result = await self.api_client.review_company(
            company_data=company,
            system_prompt=prompt_data['system_prompt'],
            few_shot_examples=prompt_data['few_shot_examples'],
            company_context=prompt_data['company_context'],
            prompt_version=prompt_data['prompt_version']
        )

        if not result.success:
            raise Exception(result.error_message or "API call failed")

        # Log audit record
        await self._log_audit(company, result, prompt_data)

        # Apply decision (audit mode: auto-apply if confidence is high)
        if result.confidence >= CLAUDE_CONFIDENCE_THRESHOLD:
            await self._apply_decision(company, result)
            logger.info(
                f"✓ Auto-applied: {company_id} -> {result.decision} "
                f"(confidence: {result.confidence:.2f})"
            )
        else:
            logger.info(
                f"⚠ Low confidence: {company_id} -> {result.decision} "
                f"(confidence: {result.confidence:.2f}) - NOT auto-applied"
            )

        # Update queue status
        await self._mark_queue_completed(company_id)

        # Update stats
        self.stats.record_success(result)

        # Track rate limits
        await self._update_rate_limits(result)

    async def _apply_decision(self, company: dict, result: ClaudeReviewResult):
        """
        Apply Claude's decision to company metadata.

        Updates parse_metadata with Claude review, label, and standardized name.
        """
        company_id = company.get('id')

        # Build claude_review metadata (verification + standardization)
        claude_review = {
            'reviewed': True,
            'reviewed_at': datetime.now().isoformat(),
            'decision': result.decision,
            'confidence': result.confidence,
            'reasoning': result.reasoning,
            'prompt_version': result.raw_response.get('model', 'unknown'),
            'overridden_by_human': False,
            # Standardization data (for training)
            'standardized_name': result.standardized_name,
            'standardization_confidence': result.standardization_confidence,
            'standardization_source': result.standardization_source,
            'standardization_reasoning': result.standardization_reasoning
        }

        # Determine label
        if result.decision == 'approve':
            label = 'provider'
        elif result.decision == 'deny':
            label = 'non_provider'
        else:
            label = None

        # Update database - include standardized_name column if we have one
        if result.standardized_name and result.standardization_confidence >= 0.7:
            update_query = """
                UPDATE companies
                SET parse_metadata = jsonb_set(
                    jsonb_set(
                        parse_metadata,
                        '{verification,claude_review}',
                        CAST(:claude_review AS jsonb)
                    ),
                    '{verification,labels,claude}',
                    CAST(:label AS jsonb)
                ),
                standardized_name = :std_name,
                standardized_name_source = 'claude',
                standardized_name_confidence = :std_confidence
                WHERE id = :company_id
            """
            params = {
                'claude_review': json.dumps(claude_review),
                'label': json.dumps(label) if label else 'null',
                'company_id': company_id,
                'std_name': result.standardized_name,
                'std_confidence': result.standardization_confidence
            }
        else:
            update_query = """
                UPDATE companies
                SET parse_metadata = jsonb_set(
                    jsonb_set(
                        parse_metadata,
                        '{verification,claude_review}',
                        CAST(:claude_review AS jsonb)
                    ),
                    '{verification,labels,claude}',
                    CAST(:label AS jsonb)
                )
                WHERE id = :company_id
            """
            params = {
                'claude_review': json.dumps(claude_review),
                'label': json.dumps(label) if label else 'null',
                'company_id': company_id
            }

        with self.db_manager.get_session() as session:
            session.execute(text(update_query), params)
            # commit handled by context manager

        if result.standardized_name:
            logger.debug(f"Applied decision + standardization to company {company_id}: '{result.standardized_name}'")
        else:
            logger.debug(f"Applied decision to company {company_id}")

    async def _log_audit(
        self,
        company: dict,
        result: ClaudeReviewResult,
        prompt_data: dict
    ):
        """Log audit record to database (verification + standardization for training)."""
        company_id = company.get('id')
        metadata = company.get('parse_metadata', {})
        verification = metadata.get('verification', {})

        # Build standardization data for training export
        standardization_data = {
            'standardized_name': result.standardized_name,
            'confidence': result.standardization_confidence,
            'source': result.standardization_source,
            'reasoning': result.standardization_reasoning
        }

        insert_query = """
            INSERT INTO claude_review_audit (
                company_id,
                reviewed_at,
                input_score,
                input_metadata,
                prompt_version,
                decision,
                confidence,
                reasoning,
                primary_services,
                identified_red_flags,
                is_provider,
                standardized_name,
                standardization_confidence,
                standardization_source,
                standardization_reasoning,
                raw_response,
                api_latency_ms,
                tokens_input,
                tokens_output,
                cached_tokens,
                cost_estimate
            ) VALUES (
                :company_id,
                NOW(),
                :input_score,
                :input_metadata,
                :prompt_version,
                :decision,
                :confidence,
                :reasoning,
                :primary_services,
                :identified_red_flags,
                :is_provider,
                :standardized_name,
                :standardization_confidence,
                :standardization_source,
                :standardization_reasoning,
                :raw_response,
                :api_latency_ms,
                :tokens_input,
                :tokens_output,
                :cached_tokens,
                :cost_estimate
            )
        """

        with self.db_manager.get_session() as session:
            session.execute(
                text(insert_query),
                {
                    'company_id': company_id,
                    'input_score': float(verification.get('final_score', 0.0)),
                    'input_metadata': json.dumps(verification),
                    'prompt_version': prompt_data['prompt_version'],
                    'decision': result.decision,
                    'confidence': result.confidence,
                    'reasoning': result.reasoning,
                    'primary_services': result.primary_services,
                    'identified_red_flags': result.identified_red_flags,
                    'is_provider': result.is_provider,
                    'standardized_name': result.standardized_name,
                    'standardization_confidence': result.standardization_confidence,
                    'standardization_source': result.standardization_source,
                    'standardization_reasoning': result.standardization_reasoning,
                    'raw_response': json.dumps(result.raw_response),
                    'api_latency_ms': result.api_latency_ms,
                    'tokens_input': result.tokens_input,
                    'tokens_output': result.tokens_output,
                    'cached_tokens': result.cached_tokens,
                    'cost_estimate': result.cost_estimate
                }
            )
            # commit handled by context manager

    async def _mark_queue_completed(self, company_id: int):
        """Mark queue entry as completed."""
        update_query = """
            UPDATE claude_review_queue
            SET status = 'completed',
                processed_at = NOW()
            WHERE company_id = :company_id
              AND status = 'processing'
        """

        with self.db_manager.get_session() as session:
            session.execute(text(update_query), {'company_id': company_id})
            # commit handled by context manager

    async def _handle_error(self, company: dict, error_message: str):
        """Handle processing error."""
        company_id = company.get('id')
        self.stats.record_error()

        # Update queue with error
        update_query = """
            UPDATE claude_review_queue
            SET status = 'failed',
                error_message = :error,
                last_error_at = NOW(),
                retry_count = retry_count + 1
            WHERE company_id = :company_id
              AND status = 'processing'
        """

        with self.db_manager.get_session() as session:
            session.execute(
                text(update_query),
                {'error': error_message, 'company_id': company_id}
            )
            # commit handled by context manager

    async def _check_safety_limits(self) -> bool:
        """Check if we've exceeded daily safety limits."""
        # Get today's stats
        query = """
            SELECT
                COUNT(*) as review_count,
                COALESCE(SUM(cost_estimate), 0) as total_cost
            FROM claude_review_audit
            WHERE reviewed_at >= CURRENT_DATE
        """

        with self.db_manager.get_session() as session:
            result = session.execute(text(query))
            row = result.fetchone()
            review_count, total_cost = row

        # Check limits
        if review_count >= self.daily_review_limit:
            logger.warning(f"Daily review limit reached: {review_count}/{self.daily_review_limit}")
            return False

        if total_cost >= self.daily_cost_limit:
            logger.warning(f"Daily cost limit reached: ${total_cost:.2f}/${self.daily_cost_limit:.2f}")
            return False

        return True

    async def _update_rate_limits(self, result: ClaudeReviewResult):
        """Update rate limit tracking table."""
        query = """
            INSERT INTO claude_rate_limits (
                hour_bucket,
                requests_made,
                tokens_input,
                tokens_output,
                cached_tokens,
                cost_estimate,
                updated_at
            ) VALUES (
                date_trunc('hour', NOW()),
                1,
                :tokens_input,
                :tokens_output,
                :cached_tokens,
                :cost_estimate,
                NOW()
            )
            ON CONFLICT (hour_bucket) DO UPDATE SET
                requests_made = claude_rate_limits.requests_made + 1,
                tokens_input = claude_rate_limits.tokens_input + :tokens_input,
                tokens_output = claude_rate_limits.tokens_output + :tokens_output,
                cached_tokens = claude_rate_limits.cached_tokens + :cached_tokens,
                cost_estimate = claude_rate_limits.cost_estimate + :cost_estimate,
                updated_at = NOW()
        """

        with self.db_manager.get_session() as session:
            session.execute(
                text(query),
                {
                    'tokens_input': result.tokens_input,
                    'tokens_output': result.tokens_output,
                    'cached_tokens': result.cached_tokens,
                    'cost_estimate': result.cost_estimate
                }
            )
            # commit handled by context manager

    async def _run_socket_server(self):
        """Run Unix socket server for status/control."""
        # Remove old socket if exists
        if os.path.exists(CLAUDE_SOCKET_PATH):
            os.remove(CLAUDE_SOCKET_PATH)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(CLAUDE_SOCKET_PATH)
        server.listen(1)
        server.setblocking(False)

        logger.info(f"Socket server listening on {CLAUDE_SOCKET_PATH}")

        while self.running:
            try:
                # Accept connection (non-blocking)
                conn, _ = await asyncio.get_event_loop().sock_accept(server)

                # Receive command
                data = await asyncio.get_event_loop().sock_recv(conn, 1024)
                command = data.decode('utf-8').strip()

                # Handle command
                response = await self._handle_socket_command(command)

                # Send response
                await asyncio.get_event_loop().sock_sendall(conn, response.encode('utf-8'))
                conn.close()

            except BlockingIOError:
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Socket server error: {e}")
                await asyncio.sleep(1)

        server.close()
        os.remove(CLAUDE_SOCKET_PATH)

    async def _handle_socket_command(self, command: str) -> str:
        """Handle socket command."""
        if command == 'status':
            stats = self.stats.get_summary()
            return json.dumps(stats, indent=2)
        elif command == 'pause':
            self.paused = True
            return "Service paused"
        elif command == 'resume':
            self.paused = False
            return "Service resumed"
        elif command == 'shutdown':
            self.running = False
            return "Shutting down..."
        else:
            return f"Unknown command: {command}"

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down Claude service...")

        # Print final stats
        stats = self.stats.get_summary()
        logger.info("=" * 70)
        logger.info("FINAL STATISTICS")
        logger.info("=" * 70)
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")
        logger.info("=" * 70)

        logger.info("Claude service stopped")


# ==============================================================================
# MAIN
# ==============================================================================

async def main():
    """Main entry point."""
    service = ClaudeService()
    await service.start()


if __name__ == "__main__":
    asyncio.run(main())
