"""
SEO Intelligence Governance Service

Provides change_log integration for all SEO scrapers, ensuring that all proposed
changes go through the review-based approval workflow.

All SEO data modifications should flow through this service to maintain governance
and provide AI-assisted review capabilities.

Usage:
    from seo_intelligence.services.governance import propose_change, get_pending_changes

    # Propose a change
    change_id = propose_change(
        table_name='citations',
        operation='update',
        record_id=123,
        proposed_data={'rating_value': 4.5, 'rating_count': 87},
        change_type='citations',
        source='review_detail_scraper'
    )

    # Later, approve/reject via GUI or CLI
    approve_change(change_id)
"""

import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from runner.logging_setup import get_logger

# Load environment
load_dotenv()

logger = get_logger("seo_governance")


class ChangeType(str, Enum):
    """Standard change type vocabulary for SEO intelligence."""
    CITATIONS = "citations"
    TECHNICAL_SEO = "technical_seo"
    ONPAGE = "onpage"
    BACKLINKS = "backlinks"
    SERP_TRACKING = "serp_tracking"
    COMPETITOR_ANALYSIS = "competitor_analysis"
    REVIEWS = "reviews"
    UNLINKED_MENTIONS = "unlinked_mentions"


class ChangeStatus(str, Enum):
    """Change approval status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"  # Approved and applied to target table


class SEOGovernanceService:
    """
    Governance service for SEO intelligence data changes.

    All SEO scrapers should use this service to propose changes instead of
    directly modifying tables. This enables:
    - Human review of AI-suggested changes
    - Audit trail of all modifications
    - Batch approval/rejection workflows
    - AI-assisted review recommendations
    """

    def __init__(self):
        """Initialize governance service."""
        # Database connection
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set - governance operations disabled")

        logger.info("SEOGovernanceService initialized")

    def propose_change(
        self,
        table_name: str,
        operation: str,
        proposed_data: Dict[str, Any],
        change_type: ChangeType,
        source: str,
        record_id: Optional[int] = None,
        metadata: Optional[Dict] = None,
        reason: Optional[str] = None
    ) -> Optional[int]:
        """
        Propose a change to the change_log for review.

        Args:
            table_name: Target table name (e.g., 'citations', 'competitor_pages')
            operation: 'insert', 'update', or 'delete'
            proposed_data: Data to be inserted/updated (JSONB)
            change_type: Change type from ChangeType enum
            source: Source identifier (e.g., 'review_detail_scraper', 'citation_crawler')
            record_id: Primary key of record being updated/deleted (for updates/deletes)
            metadata: Additional metadata (e.g., scraper config, confidence scores)
            reason: Human-readable reason for the change

        Returns:
            change_id if successful, None otherwise
        """
        if not self.engine:
            logger.error("Cannot propose change - database not configured")
            return None

        try:
            with Session(self.engine) as session:
                # Convert dicts to JSON strings
                proposed_data_json = json.dumps(proposed_data)
                metadata_json = json.dumps(metadata or {})

                # Insert into change_log
                result = session.execute(
                    text("""
                        INSERT INTO change_log (
                            table_name,
                            operation,
                            record_id,
                            proposed_data,
                            change_type,
                            source,
                            status,
                            proposed_at,
                            metadata,
                            reason
                        ) VALUES (
                            :table_name,
                            :operation,
                            :record_id,
                            :proposed_data,
                            :change_type,
                            :source,
                            :status,
                            NOW(),
                            :metadata,
                            :reason
                        )
                        RETURNING change_id
                    """),
                    {
                        "table_name": table_name,
                        "operation": operation,
                        "record_id": record_id,
                        "proposed_data": proposed_data_json,
                        "change_type": change_type.value,
                        "source": source,
                        "status": ChangeStatus.PENDING.value,
                        "metadata": metadata_json,
                        "reason": reason
                    }
                )

                change_id = result.scalar()
                session.commit()

                logger.info(
                    f"Proposed change: {operation} on {table_name} "
                    f"(change_id={change_id}, type={change_type.value})"
                )

                return change_id

        except Exception as e:
            logger.error(f"Error proposing change: {e}", exc_info=True)
            return None

    def get_pending_changes(
        self,
        change_type: Optional[ChangeType] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get pending changes awaiting review.

        Args:
            change_type: Filter by specific change type (None = all types)
            limit: Maximum changes to return

        Returns:
            List of pending change dictionaries
        """
        if not self.engine:
            logger.error("Cannot get pending changes - database not configured")
            return []

        try:
            with Session(self.engine) as session:
                query = """
                    SELECT
                        change_id,
                        table_name,
                        operation,
                        record_id,
                        proposed_data,
                        change_type,
                        source,
                        status,
                        proposed_at,
                        metadata,
                        reason
                    FROM change_log
                    WHERE status = :status
                """

                params = {"status": ChangeStatus.PENDING.value, "limit": limit}

                if change_type:
                    query += " AND change_type = :change_type"
                    params["change_type"] = change_type.value

                query += " ORDER BY proposed_at DESC LIMIT :limit"

                result = session.execute(text(query), params)

                changes = []
                for row in result:
                    changes.append({
                        'change_id': row[0],
                        'table_name': row[1],
                        'operation': row[2],
                        'record_id': row[3],
                        'proposed_data': row[4],
                        'change_type': row[5],
                        'source': row[6],
                        'status': row[7],
                        'proposed_at': row[8],
                        'metadata': row[9],
                        'reason': row[10]
                    })

                logger.info(f"Found {len(changes)} pending changes")
                return changes

        except Exception as e:
            logger.error(f"Error getting pending changes: {e}", exc_info=True)
            return []

    def approve_change(
        self,
        change_id: int,
        reviewed_by: Optional[str] = None,
        apply_immediately: bool = True
    ) -> bool:
        """
        Approve a proposed change.

        Args:
            change_id: Change ID to approve
            reviewed_by: Identifier of reviewer (user ID, 'ai_assistant', etc.)
            apply_immediately: If True, apply the change to target table

        Returns:
            True if approved successfully
        """
        if not self.engine:
            logger.error("Cannot approve change - database not configured")
            return False

        try:
            with Session(self.engine) as session:
                # Update change_log status
                session.execute(
                    text("""
                        UPDATE change_log
                        SET
                            status = :status,
                            reviewed_at = NOW(),
                            reviewed_by = :reviewed_by
                        WHERE change_id = :change_id
                    """),
                    {
                        "change_id": change_id,
                        "status": ChangeStatus.APPROVED.value,
                        "reviewed_by": reviewed_by
                    }
                )

                session.commit()

                logger.info(f"Approved change {change_id}")

                # Apply change if requested
                if apply_immediately:
                    return self.apply_change(change_id)

                return True

        except Exception as e:
            logger.error(f"Error approving change {change_id}: {e}", exc_info=True)
            return False

    def reject_change(
        self,
        change_id: int,
        reviewed_by: Optional[str] = None,
        rejection_reason: Optional[str] = None
    ) -> bool:
        """
        Reject a proposed change.

        Args:
            change_id: Change ID to reject
            reviewed_by: Identifier of reviewer
            rejection_reason: Reason for rejection

        Returns:
            True if rejected successfully
        """
        if not self.engine:
            logger.error("Cannot reject change - database not configured")
            return False

        try:
            with Session(self.engine) as session:
                # Build metadata update
                metadata_update = {}
                if rejection_reason:
                    metadata_update['rejection_reason'] = rejection_reason

                metadata_update_json = json.dumps(metadata_update)

                session.execute(
                    text("""
                        UPDATE change_log
                        SET
                            status = :status,
                            reviewed_at = NOW(),
                            reviewed_by = :reviewed_by,
                            metadata = COALESCE(metadata, '{}') || :metadata_update
                        WHERE change_id = :change_id
                    """),
                    {
                        "change_id": change_id,
                        "status": ChangeStatus.REJECTED.value,
                        "reviewed_by": reviewed_by,
                        "metadata_update": metadata_update_json
                    }
                )

                session.commit()

                logger.info(f"Rejected change {change_id}: {rejection_reason}")
                return True

        except Exception as e:
            logger.error(f"Error rejecting change {change_id}: {e}", exc_info=True)
            return False

    def apply_change(self, change_id: int) -> bool:
        """
        Apply an approved change to its target table.

        Args:
            change_id: Change ID to apply

        Returns:
            True if applied successfully
        """
        if not self.engine:
            logger.error("Cannot apply change - database not configured")
            return False

        try:
            with Session(self.engine) as session:
                # Get change details
                result = session.execute(
                    text("""
                        SELECT
                            table_name,
                            operation,
                            record_id,
                            proposed_data,
                            status
                        FROM change_log
                        WHERE change_id = :change_id
                    """),
                    {"change_id": change_id}
                )

                row = result.fetchone()
                if not row:
                    logger.error(f"Change {change_id} not found")
                    return False

                table_name, operation, record_id, proposed_data, status = row

                # Only apply approved changes
                if status != ChangeStatus.APPROVED.value:
                    logger.warning(f"Change {change_id} is not approved (status={status})")
                    return False

                # Apply the change based on operation
                if operation == 'insert':
                    # Build INSERT statement dynamically
                    columns = ', '.join(proposed_data.keys())
                    placeholders = ', '.join([f':{k}' for k in proposed_data.keys()])

                    session.execute(
                        text(f"""
                            INSERT INTO {table_name} ({columns})
                            VALUES ({placeholders})
                        """),
                        proposed_data
                    )

                elif operation == 'update':
                    # Build UPDATE statement dynamically
                    set_clause = ', '.join([f"{k} = :{k}" for k in proposed_data.keys()])
                    primary_key_col = self._get_primary_key_column(table_name)

                    session.execute(
                        text(f"""
                            UPDATE {table_name}
                            SET {set_clause}
                            WHERE {primary_key_col} = :record_id
                        """),
                        {**proposed_data, 'record_id': record_id}
                    )

                elif operation == 'delete':
                    primary_key_col = self._get_primary_key_column(table_name)

                    session.execute(
                        text(f"""
                            DELETE FROM {table_name}
                            WHERE {primary_key_col} = :record_id
                        """),
                        {'record_id': record_id}
                    )

                # Mark change as applied
                session.execute(
                    text("""
                        UPDATE change_log
                        SET
                            status = :status,
                            applied_at = NOW()
                        WHERE change_id = :change_id
                    """),
                    {
                        "change_id": change_id,
                        "status": ChangeStatus.APPLIED.value
                    }
                )

                session.commit()

                logger.info(f"Applied change {change_id}: {operation} on {table_name}")
                return True

        except Exception as e:
            logger.error(f"Error applying change {change_id}: {e}", exc_info=True)
            return False

    def _get_primary_key_column(self, table_name: str) -> str:
        """
        Get primary key column name for a table.

        Args:
            table_name: Table name

        Returns:
            Primary key column name
        """
        # Standard primary key naming convention
        pk_map = {
            'search_queries': 'query_id',
            'serp_snapshots': 'snapshot_id',
            'serp_results': 'result_id',
            'serp_paa': 'paa_id',
            'competitors': 'competitor_id',
            'competitor_pages': 'page_id',
            'backlinks': 'backlink_id',
            'referring_domains': 'domain_id',
            'citations': 'citation_id',
            'page_audits': 'audit_id',
            'audit_issues': 'issue_id',
            'change_log': 'change_id',
            'task_logs': 'task_id'
        }

        return pk_map.get(table_name, 'id')

    def bulk_approve_changes(
        self,
        change_ids: List[int],
        reviewed_by: Optional[str] = None,
        apply_immediately: bool = True
    ) -> Dict[str, int]:
        """
        Approve multiple changes in bulk.

        Args:
            change_ids: List of change IDs to approve
            reviewed_by: Identifier of reviewer
            apply_immediately: If True, apply changes to target tables

        Returns:
            Dictionary with counts: {'approved': N, 'applied': M, 'failed': K}
        """
        counts = {'approved': 0, 'applied': 0, 'failed': 0}

        for change_id in change_ids:
            success = self.approve_change(change_id, reviewed_by, apply_immediately)
            if success:
                counts['approved'] += 1
                if apply_immediately:
                    counts['applied'] += 1
            else:
                counts['failed'] += 1

        logger.info(f"Bulk approval complete: {counts}")
        return counts


# Global service instance
_governance_service = None


def get_governance_service() -> SEOGovernanceService:
    """
    Get global governance service instance.

    Returns:
        SEOGovernanceService instance
    """
    global _governance_service
    if _governance_service is None:
        _governance_service = SEOGovernanceService()
    return _governance_service


# Convenience functions
def propose_change(
    table_name: str,
    operation: str,
    proposed_data: Dict[str, Any],
    change_type: ChangeType,
    source: str,
    **kwargs
) -> Optional[int]:
    """
    Propose a change (convenience wrapper).

    See SEOGovernanceService.propose_change for full documentation.
    """
    service = get_governance_service()
    return service.propose_change(
        table_name=table_name,
        operation=operation,
        proposed_data=proposed_data,
        change_type=change_type,
        source=source,
        **kwargs
    )


def get_pending_changes(change_type: Optional[ChangeType] = None, limit: int = 100) -> List[Dict]:
    """
    Get pending changes (convenience wrapper).

    See SEOGovernanceService.get_pending_changes for full documentation.
    """
    service = get_governance_service()
    return service.get_pending_changes(change_type=change_type, limit=limit)


def approve_change(change_id: int, **kwargs) -> bool:
    """
    Approve a change (convenience wrapper).

    See SEOGovernanceService.approve_change for full documentation.
    """
    service = get_governance_service()
    return service.approve_change(change_id=change_id, **kwargs)


def reject_change(change_id: int, **kwargs) -> bool:
    """
    Reject a change (convenience wrapper).

    See SEOGovernanceService.reject_change for full documentation.
    """
    service = get_governance_service()
    return service.reject_change(change_id=change_id, **kwargs)


# CLI interface for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SEO Governance Service CLI")
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # List pending changes
    list_parser = subparsers.add_parser('list', help='List pending changes')
    list_parser.add_argument('--type', choices=[t.value for t in ChangeType], help='Filter by change type')
    list_parser.add_argument('--limit', type=int, default=20, help='Maximum changes to show')

    # Approve change
    approve_parser = subparsers.add_parser('approve', help='Approve a change')
    approve_parser.add_argument('change_id', type=int, help='Change ID to approve')
    approve_parser.add_argument('--reviewer', default='cli_user', help='Reviewer identifier')
    approve_parser.add_argument('--no-apply', action='store_true', help='Do not apply immediately')

    # Reject change
    reject_parser = subparsers.add_parser('reject', help='Reject a change')
    reject_parser.add_argument('change_id', type=int, help='Change ID to reject')
    reject_parser.add_argument('--reason', help='Rejection reason')
    reject_parser.add_argument('--reviewer', default='cli_user', help='Reviewer identifier')

    args = parser.parse_args()

    if args.command == 'list':
        change_type = ChangeType(args.type) if args.type else None
        changes = get_pending_changes(change_type=change_type, limit=args.limit)

        print(f"\n{len(changes)} pending changes:\n")
        for change in changes:
            print(f"ID {change['change_id']}: {change['operation']} on {change['table_name']}")
            print(f"  Type: {change['change_type']}, Source: {change['source']}")
            print(f"  Proposed: {change['proposed_at']}")
            if change['reason']:
                print(f"  Reason: {change['reason']}")
            print()

    elif args.command == 'approve':
        success = approve_change(
            args.change_id,
            reviewed_by=args.reviewer,
            apply_immediately=not args.no_apply
        )
        if success:
            print(f"✓ Change {args.change_id} approved")
        else:
            print(f"✗ Failed to approve change {args.change_id}")

    elif args.command == 'reject':
        success = reject_change(
            args.change_id,
            reviewed_by=args.reviewer,
            rejection_reason=args.reason
        )
        if success:
            print(f"✓ Change {args.change_id} rejected")
        else:
            print(f"✗ Failed to reject change {args.change_id}")

    else:
        parser.print_help()
