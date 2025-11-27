"""
Change Manager - Governance and Review System

Implements write-only architecture where all proposed changes:
1. Go to change_log table with status='pending'
2. Require human review and approval
3. Are applied only after approval

This ensures human oversight of all SEO-related modifications.
"""

import os
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from runner.logging_setup import get_logger

# Load environment
load_dotenv()

logger = get_logger("change_manager")


class ChangeStatus(Enum):
    """Status of a proposed change."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    FAILED = "failed"


class ChangeType(Enum):
    """Types of changes that can be proposed."""
    SEO_RECOMMENDATION = "seo_recommendation"
    CONTENT_UPDATE = "content_update"
    SCHEMA_CHANGE = "schema_change"
    META_UPDATE = "meta_update"
    LINK_CHANGE = "link_change"
    CITATION_UPDATE = "citation_update"
    COMPETITOR_ACTION = "competitor_action"
    AUDIT_FIX = "audit_fix"
    OTHER = "other"


class ChangeManager:
    """
    Manager for change proposals and governance.

    All changes from the SEO intelligence system flow through this
    manager, ensuring human oversight before any modifications.
    """

    def __init__(self):
        """Initialize change manager."""
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set - database operations disabled")

        logger.info("ChangeManager initialized")

    def propose_change(
        self,
        change_type: str,
        entity_type: str,
        entity_id: Optional[int] = None,
        proposed_value: Dict[str, Any] = None,
        current_value: Dict[str, Any] = None,
        reason: str = "",
        priority: str = "medium",
        source: str = "seo_intelligence",
        metadata: Dict[str, Any] = None,
    ) -> Optional[int]:
        """
        Propose a change for review.

        Args:
            change_type: Type of change (from ChangeType enum)
            entity_type: Type of entity being changed (page, competitor, etc.)
            entity_id: ID of the entity being changed
            proposed_value: The proposed new value(s)
            current_value: The current value(s) for comparison
            reason: Human-readable reason for the change
            priority: low, medium, high, critical
            source: System/component proposing the change
            metadata: Additional context

        Returns:
            int: Change log ID, or None if failed
        """
        if not self.engine:
            logger.warning("Cannot propose change - database not configured")
            return None

        try:
            with Session(self.engine) as session:
                result = session.execute(
                    text("""
                        INSERT INTO change_log (
                            change_type, entity_type, entity_id,
                            proposed_value, current_value, reason,
                            priority, source, status, metadata
                        ) VALUES (
                            :change_type, :entity_type, :entity_id,
                            CAST(:proposed_value AS jsonb), CAST(:current_value AS jsonb), :reason,
                            :priority, :source, 'pending', CAST(:metadata AS jsonb)
                        )
                        RETURNING change_id
                    """),
                    {
                        "change_type": change_type,
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "proposed_value": json.dumps(proposed_value or {}),
                        "current_value": json.dumps(current_value or {}),
                        "reason": reason,
                        "priority": priority,
                        "source": source,
                        "metadata": json.dumps(metadata or {}),
                    }
                )
                session.commit()

                change_id = result.fetchone()[0]
                logger.info(
                    f"Change proposed: {change_type} for {entity_type} "
                    f"(ID: {change_id}, priority: {priority})"
                )

                return change_id

        except Exception as e:
            logger.error(f"Error proposing change: {e}")
            return None

    def get_pending_changes(
        self,
        change_type: Optional[str] = None,
        priority: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get pending changes for review.

        Args:
            change_type: Filter by change type
            priority: Filter by priority
            limit: Maximum number of results

        Returns:
            List of pending change records
        """
        if not self.engine:
            return []

        try:
            with Session(self.engine) as session:
                query = """
                    SELECT change_id, change_type, entity_type, entity_id,
                           proposed_value, current_value, reason, priority,
                           source, created_at, metadata
                    FROM change_log
                    WHERE status = 'pending'
                """
                params = {"limit": limit}

                if change_type:
                    query += " AND change_type = :change_type"
                    params["change_type"] = change_type

                if priority:
                    query += " AND priority = :priority"
                    params["priority"] = priority

                query += " ORDER BY CASE priority "
                query += "WHEN 'critical' THEN 1 WHEN 'high' THEN 2 "
                query += "WHEN 'medium' THEN 3 ELSE 4 END, created_at"
                query += " LIMIT :limit"

                result = session.execute(text(query), params)

                changes = []
                for row in result.fetchall():
                    changes.append({
                        "change_id": row[0],
                        "change_type": row[1],
                        "entity_type": row[2],
                        "entity_id": row[3],
                        "proposed_value": row[4],
                        "current_value": row[5],
                        "reason": row[6],
                        "priority": row[7],
                        "source": row[8],
                        "created_at": row[9].isoformat() if row[9] else None,
                        "metadata": row[10],
                    })

                return changes

        except Exception as e:
            logger.error(f"Error getting pending changes: {e}")
            return []

    def approve_change(
        self,
        change_id: int,
        reviewer: str = "admin",
        notes: str = "",
    ) -> bool:
        """
        Approve a pending change.

        Args:
            change_id: ID of the change to approve
            reviewer: Name/ID of the reviewer
            notes: Optional reviewer notes

        Returns:
            bool: Success status
        """
        if not self.engine:
            return False

        try:
            with Session(self.engine) as session:
                result = session.execute(
                    text("""
                        UPDATE change_log
                        SET status = 'approved',
                            reviewed_at = NOW(),
                            reviewed_by = :reviewer,
                            review_notes = :notes
                        WHERE change_id = :change_id
                        AND status = 'pending'
                        RETURNING change_id
                    """),
                    {
                        "change_id": change_id,
                        "reviewer": reviewer,
                        "notes": notes,
                    }
                )
                session.commit()

                if result.fetchone():
                    logger.info(f"Change {change_id} approved by {reviewer}")
                    return True
                else:
                    logger.warning(f"Change {change_id} not found or not pending")
                    return False

        except Exception as e:
            logger.error(f"Error approving change {change_id}: {e}")
            return False

    def reject_change(
        self,
        change_id: int,
        reviewer: str = "admin",
        reason: str = "",
    ) -> bool:
        """
        Reject a pending change.

        Args:
            change_id: ID of the change to reject
            reviewer: Name/ID of the reviewer
            reason: Reason for rejection

        Returns:
            bool: Success status
        """
        if not self.engine:
            return False

        try:
            with Session(self.engine) as session:
                result = session.execute(
                    text("""
                        UPDATE change_log
                        SET status = 'rejected',
                            reviewed_at = NOW(),
                            reviewed_by = :reviewer,
                            review_notes = :reason
                        WHERE change_id = :change_id
                        AND status = 'pending'
                        RETURNING change_id
                    """),
                    {
                        "change_id": change_id,
                        "reviewer": reviewer,
                        "reason": reason,
                    }
                )
                session.commit()

                if result.fetchone():
                    logger.info(f"Change {change_id} rejected by {reviewer}")
                    return True
                else:
                    logger.warning(f"Change {change_id} not found or not pending")
                    return False

        except Exception as e:
            logger.error(f"Error rejecting change {change_id}: {e}")
            return False

    def mark_applied(
        self,
        change_id: int,
        result_notes: str = "",
    ) -> bool:
        """
        Mark an approved change as applied.

        Args:
            change_id: ID of the change
            result_notes: Notes about the application result

        Returns:
            bool: Success status
        """
        if not self.engine:
            return False

        try:
            with Session(self.engine) as session:
                result = session.execute(
                    text("""
                        UPDATE change_log
                        SET status = 'applied',
                            applied_at = NOW(),
                            result_notes = :notes
                        WHERE change_id = :change_id
                        AND status = 'approved'
                        RETURNING change_id
                    """),
                    {
                        "change_id": change_id,
                        "notes": result_notes,
                    }
                )
                session.commit()

                if result.fetchone():
                    logger.info(f"Change {change_id} marked as applied")
                    return True
                else:
                    logger.warning(f"Change {change_id} not found or not approved")
                    return False

        except Exception as e:
            logger.error(f"Error marking change {change_id} as applied: {e}")
            return False

    def mark_failed(
        self,
        change_id: int,
        error_message: str = "",
    ) -> bool:
        """
        Mark a change as failed to apply.

        Args:
            change_id: ID of the change
            error_message: Error details

        Returns:
            bool: Success status
        """
        if not self.engine:
            return False

        try:
            with Session(self.engine) as session:
                result = session.execute(
                    text("""
                        UPDATE change_log
                        SET status = 'failed',
                            applied_at = NOW(),
                            result_notes = :error
                        WHERE change_id = :change_id
                        AND status = 'approved'
                        RETURNING change_id
                    """),
                    {
                        "change_id": change_id,
                        "error": error_message,
                    }
                )
                session.commit()

                if result.fetchone():
                    logger.warning(f"Change {change_id} marked as failed: {error_message}")
                    return True
                return False

        except Exception as e:
            logger.error(f"Error marking change {change_id} as failed: {e}")
            return False

    def get_change_history(
        self,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        status: Optional[str] = None,
        days: int = 30,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get change history with filters.

        Args:
            entity_type: Filter by entity type
            entity_id: Filter by entity ID
            status: Filter by status
            days: Number of days to look back
            limit: Maximum results

        Returns:
            List of change records
        """
        if not self.engine:
            return []

        try:
            with Session(self.engine) as session:
                query = """
                    SELECT change_id, change_type, entity_type, entity_id,
                           proposed_value, current_value, reason, priority,
                           source, status, created_at, reviewed_at,
                           reviewed_by, review_notes, applied_at, result_notes
                    FROM change_log
                    WHERE created_at >= NOW() - INTERVAL ':days days'
                """
                params = {"days": days, "limit": limit}

                # Build dynamic query
                conditions = []
                if entity_type:
                    conditions.append("entity_type = :entity_type")
                    params["entity_type"] = entity_type

                if entity_id:
                    conditions.append("entity_id = :entity_id")
                    params["entity_id"] = entity_id

                if status:
                    conditions.append("status = :status")
                    params["status"] = status

                if conditions:
                    query = query.replace(
                        "WHERE created_at",
                        f"WHERE {' AND '.join(conditions)} AND created_at"
                    )

                query += " ORDER BY created_at DESC LIMIT :limit"

                # Execute with proper interval syntax
                query = query.replace(":days days", f"{days} days")

                result = session.execute(text(query), params)

                history = []
                for row in result.fetchall():
                    history.append({
                        "change_id": row[0],
                        "change_type": row[1],
                        "entity_type": row[2],
                        "entity_id": row[3],
                        "proposed_value": row[4],
                        "current_value": row[5],
                        "reason": row[6],
                        "priority": row[7],
                        "source": row[8],
                        "status": row[9],
                        "created_at": row[10].isoformat() if row[10] else None,
                        "reviewed_at": row[11].isoformat() if row[11] else None,
                        "reviewed_by": row[12],
                        "review_notes": row[13],
                        "applied_at": row[14].isoformat() if row[14] else None,
                        "result_notes": row[15],
                    })

                return history

        except Exception as e:
            logger.error(f"Error getting change history: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get change log statistics."""
        if not self.engine:
            return {}

        try:
            with Session(self.engine) as session:
                # Get counts by status
                result = session.execute(
                    text("""
                        SELECT status, COUNT(*) as count
                        FROM change_log
                        GROUP BY status
                    """)
                )
                status_counts = {row[0]: row[1] for row in result.fetchall()}

                # Get counts by priority for pending
                result = session.execute(
                    text("""
                        SELECT priority, COUNT(*) as count
                        FROM change_log
                        WHERE status = 'pending'
                        GROUP BY priority
                    """)
                )
                priority_counts = {row[0]: row[1] for row in result.fetchall()}

                # Get recent activity
                result = session.execute(
                    text("""
                        SELECT COUNT(*) FROM change_log
                        WHERE created_at >= NOW() - INTERVAL '24 hours'
                    """)
                )
                recent_24h = result.fetchone()[0]

                return {
                    "by_status": status_counts,
                    "pending_by_priority": priority_counts,
                    "total_pending": status_counts.get("pending", 0),
                    "total_approved": status_counts.get("approved", 0),
                    "total_applied": status_counts.get("applied", 0),
                    "total_rejected": status_counts.get("rejected", 0),
                    "changes_last_24h": recent_24h,
                }

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}


# Module-level singleton
_change_manager_instance = None


def get_change_manager() -> ChangeManager:
    """Get or create the singleton ChangeManager instance."""
    global _change_manager_instance

    if _change_manager_instance is None:
        _change_manager_instance = ChangeManager()

    return _change_manager_instance


def main():
    """Demo/CLI interface for change manager."""
    import argparse

    parser = argparse.ArgumentParser(description="SEO Change Manager")
    parser.add_argument("--pending", action="store_true", help="List pending changes")
    parser.add_argument("--approve", type=int, help="Approve change by ID")
    parser.add_argument("--reject", type=int, help="Reject change by ID")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--demo", action="store_true", help="Run demo mode")

    args = parser.parse_args()

    manager = get_change_manager()

    if args.demo:
        logger.info("=" * 60)
        logger.info("SEO Change Manager - Governance System")
        logger.info("=" * 60)
        logger.info("")
        logger.info("All changes flow through this system for human review:")
        logger.info("  1. propose_change() - Creates pending change")
        logger.info("  2. get_pending_changes() - View changes awaiting review")
        logger.info("  3. approve_change() / reject_change() - Review decision")
        logger.info("  4. mark_applied() - Confirm successful application")
        logger.info("")
        logger.info("Change types supported:")
        for ct in ChangeType:
            logger.info(f"  - {ct.value}")
        logger.info("")
        logger.info("Example:")
        logger.info("  manager.propose_change(")
        logger.info("      change_type='meta_update',")
        logger.info("      entity_type='page',")
        logger.info("      entity_id=123,")
        logger.info("      proposed_value={'title': 'New Title'},")
        logger.info("      current_value={'title': 'Old Title'},")
        logger.info("      reason='Improve SEO score'")
        logger.info("  )")
        logger.info("")
        logger.info("=" * 60)
        return

    if args.stats:
        stats = manager.get_stats()
        logger.info("Change Log Statistics:")
        logger.info(f"  Pending: {stats.get('total_pending', 0)}")
        logger.info(f"  Approved: {stats.get('total_approved', 0)}")
        logger.info(f"  Applied: {stats.get('total_applied', 0)}")
        logger.info(f"  Rejected: {stats.get('total_rejected', 0)}")
        logger.info(f"  Last 24h: {stats.get('changes_last_24h', 0)}")
        return

    if args.pending:
        changes = manager.get_pending_changes()
        logger.info(f"Pending changes: {len(changes)}")
        for change in changes[:10]:
            logger.info(
                f"  [{change['change_id']}] {change['change_type']} - "
                f"{change['entity_type']} ({change['priority']})"
            )
            logger.info(f"       Reason: {change['reason'][:50]}...")
        return

    if args.approve:
        if manager.approve_change(args.approve):
            logger.info(f"Change {args.approve} approved")
        else:
            logger.error(f"Failed to approve change {args.approve}")
        return

    if args.reject:
        if manager.reject_change(args.reject, reason="Rejected via CLI"):
            logger.info(f"Change {args.reject} rejected")
        else:
            logger.error(f"Failed to reject change {args.reject}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
