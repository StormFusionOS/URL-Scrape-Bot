"""
Local Competitors API Service
Handles all database operations for local competitors management
"""

from sqlalchemy import text
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime

from db.database_manager import get_db_manager

# Get database manager for scraper database
db_manager = get_db_manager()

logger = logging.getLogger(__name__)


class LocalCompetitorsAPI:
    """API service for managing local competitors"""

    @staticmethod
    def get_all_competitors(node_type: Optional[str] = None,
                           industry: Optional[str] = None,
                           location: Optional[str] = None,
                           tier: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all competitors with optional filtering

        Args:
            node_type: Filter by node type ('local', 'national', 'both', or None for all)
            industry: Filter by industry
            location: Filter by location
            tier: Filter by tier ('tier1', 'tier2', 'tier3')

        Returns:
            List of competitor records
        """
        try:
            with db_manager.get_session('scraper') as session:
                # Build WHERE clause
                where_conditions = []
                params = {}

                if node_type and node_type != 'all':
                    where_conditions.append("node_type = :node_type")
                    params['node_type'] = node_type

                if industry:
                    where_conditions.append("industry = :industry")
                    params['industry'] = industry

                if location:
                    where_conditions.append("location = :location")
                    params['location'] = location

                if tier:
                    where_conditions.append("competitor_tier = :tier")
                    params['tier'] = tier

                where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""

                query = f"""
                    SELECT * FROM all_competitors_unified
                    {where_clause}
                    ORDER BY crawl_priority_score DESC
                    LIMIT 1000
                """

                result = session.execute(text(query), params)
                columns = result.keys()
                competitors = []

                for row in result:
                    competitor = dict(zip(columns, row))
                    # Convert datetime objects to strings
                    for key in ['last_crawled', 'added_date', 'last_synced_at']:
                        if key in competitor and competitor[key]:
                            competitor[key] = str(competitor[key])
                    competitors.append(competitor)

                return competitors

        except Exception as e:
            logger.error(f"Error fetching competitors: {e}")
            return []

    @staticmethod
    def get_local_competitors() -> List[Dict[str, Any]]:
        """Get only local competitors"""
        try:
            with db_manager.get_session('scraper') as session:
                query = """
                    SELECT * FROM local_competitors_dashboard
                    ORDER BY priority DESC, business_name
                """

                result = session.execute(text(query))
                columns = result.keys()
                competitors = []

                for row in result:
                    competitor = dict(zip(columns, row))
                    # Convert datetime objects to strings
                    for key in ['added_date', 'modified_date', 'last_crawled', 'last_synced_at']:
                        if key in competitor and competitor[key]:
                            competitor[key] = str(competitor[key])
                    competitors.append(competitor)

                return competitors

        except Exception as e:
            logger.error(f"Error fetching local competitors: {e}")
            return []

    @staticmethod
    def add_local_competitor(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add a new local competitor

        Args:
            data: Competitor data including business_name, url, etc.

        Returns:
            Created competitor with ID or error
        """
        try:
            with db_manager.get_session('scraper') as session:
                # Insert into local_competitors table
                query = """
                    INSERT INTO local_competitors (
                        business_name, url, industry, location,
                        address, phone, priority, tags, notes,
                        is_primary_competitor, competitor_tier,
                        estimated_monthly_traffic, status
                    ) VALUES (
                        :business_name, :url, :industry, :location,
                        :address, :phone, :priority, :tags, :notes,
                        :is_primary_competitor, :competitor_tier,
                        :estimated_monthly_traffic, :status
                    ) RETURNING local_competitor_id
                """

                # Prepare parameters with defaults
                params = {
                    'business_name': data.get('business_name'),
                    'url': data.get('url'),
                    'industry': data.get('industry'),
                    'location': data.get('location'),
                    'address': data.get('address'),
                    'phone': data.get('phone'),
                    'priority': data.get('priority', 5),
                    'tags': data.get('tags', []),
                    'notes': data.get('notes'),
                    'is_primary_competitor': data.get('is_primary_competitor', False),
                    'competitor_tier': data.get('competitor_tier'),
                    'estimated_monthly_traffic': data.get('estimated_monthly_traffic'),
                    'status': data.get('status', 'active')
                }

                result = session.execute(text(query), params)
                competitor_id = result.scalar()

                # Sync to competitor_urls for crawling
                sync_query = "SELECT sync_local_competitor_to_urls(:id)"
                session.execute(text(sync_query), {'id': competitor_id})

                session.commit()

                return {
                    'success': True,
                    'local_competitor_id': competitor_id,
                    'message': 'Local competitor added successfully'
                }

        except Exception as e:
            logger.error(f"Error adding local competitor: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def update_local_competitor(competitor_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing local competitor

        Args:
            competitor_id: ID of competitor to update
            data: Updated data

        Returns:
            Update result
        """
        try:
            with db_manager.get_session('scraper') as session:
                # Build UPDATE statement dynamically
                update_fields = []
                params = {'id': competitor_id}

                for field in ['business_name', 'url', 'industry', 'location',
                             'address', 'phone', 'priority', 'tags', 'notes',
                             'is_primary_competitor', 'competitor_tier',
                             'estimated_monthly_traffic', 'status']:
                    if field in data:
                        update_fields.append(f"{field} = :{field}")
                        params[field] = data[field]

                if not update_fields:
                    return {'success': False, 'error': 'No fields to update'}

                query = f"""
                    UPDATE local_competitors
                    SET {', '.join(update_fields)}
                    WHERE local_competitor_id = :id
                """

                session.execute(text(query), params)

                # Re-sync to competitor_urls
                sync_query = "SELECT sync_local_competitor_to_urls(:id)"
                session.execute(text(sync_query), {'id': competitor_id})

                session.commit()

                return {
                    'success': True,
                    'message': 'Local competitor updated successfully'
                }

        except Exception as e:
            logger.error(f"Error updating local competitor: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def delete_local_competitor(competitor_id: int) -> Dict[str, Any]:
        """
        Delete a local competitor (soft delete by setting status to 'archived')

        Args:
            competitor_id: ID of competitor to delete

        Returns:
            Deletion result
        """
        try:
            with db_manager.get_session('scraper') as session:
                query = """
                    UPDATE local_competitors
                    SET status = 'archived'
                    WHERE local_competitor_id = :id
                """

                session.execute(text(query), {'id': competitor_id})
                session.commit()

                return {
                    'success': True,
                    'message': 'Local competitor archived successfully'
                }

        except Exception as e:
            logger.error(f"Error deleting local competitor: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def get_competitor_stats(node_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get statistics for competitors

        Args:
            node_type: Optional filter by node type

        Returns:
            Statistics dictionary
        """
        try:
            with db_manager.get_session('scraper') as session:
                # Use the get_competitor_stats function
                query = "SELECT * FROM get_competitor_stats(:node_type, NULL, NULL, NULL)"
                result = session.execute(text(query), {'node_type': node_type})

                row = result.first()
                if row:
                    columns = result.keys()
                    stats = dict(zip(columns, row))
                    return stats

                return {}

        except Exception as e:
            logger.error(f"Error fetching competitor stats: {e}")
            return {}

    @staticmethod
    def get_performance_metrics() -> List[Dict[str, Any]]:
        """Get performance metrics by node type"""
        try:
            with db_manager.get_session('scraper') as session:
                query = """
                    SELECT * FROM competitor_performance_metrics
                    ORDER BY node_type
                """

                result = session.execute(text(query))
                columns = result.keys()
                metrics = []

                for row in result:
                    metric = dict(zip(columns, row))
                    # Convert datetime objects to strings
                    for key in ['oldest_competitor', 'newest_competitor', 'most_recent_crawl']:
                        if key in metric and metric[key]:
                            metric[key] = str(metric[key])
                    metrics.append(metric)

                return metrics

        except Exception as e:
            logger.error(f"Error fetching performance metrics: {e}")
            return []

    @staticmethod
    def sync_national_competitors() -> Dict[str, Any]:
        """
        Sync national competitors from washbot_db

        Returns:
            Sync result with count of synced competitors
        """
        try:
            with db_manager.get_session('scraper') as session:
                query = "SELECT * FROM sync_national_competitors()"
                result = session.execute(text(query))

                synced_count = 0
                errors = []

                for row in result:
                    if row[2] == 'synced':
                        synced_count += 1
                    elif row[2].startswith('error'):
                        errors.append(f"Competitor {row[0]}: {row[2]}")

                session.commit()

                return {
                    'success': True,
                    'synced_count': synced_count,
                    'errors': errors,
                    'message': f'Synced {synced_count} national competitors'
                }

        except Exception as e:
            logger.error(f"Error syncing national competitors: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def bulk_sync_local_competitors() -> Dict[str, Any]:
        """
        Sync all active local competitors to competitor_urls table

        Returns:
            Sync result
        """
        try:
            with db_manager.get_session('scraper') as session:
                query = "SELECT * FROM sync_all_local_competitors()"
                result = session.execute(text(query))

                synced_count = 0
                skipped_count = 0
                errors = []

                for row in result:
                    if row[3] == 'synced':
                        synced_count += 1
                    elif row[3] == 'skipped':
                        skipped_count += 1
                    elif row[3].startswith('error'):
                        errors.append(f"ID {row[0]}: {row[3]}")

                session.commit()

                return {
                    'success': True,
                    'synced_count': synced_count,
                    'skipped_count': skipped_count,
                    'errors': errors,
                    'message': f'Synced {synced_count} local competitors'
                }

        except Exception as e:
            logger.error(f"Error bulk syncing local competitors: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def bulk_import_competitors(competitors_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Bulk import multiple competitors at once for better performance

        Args:
            competitors_list: List of competitor data dictionaries

        Returns:
            Import results with success/error counts
        """
        try:
            success_count = 0
            error_count = 0
            errors = []
            imported_ids = []

            with db_manager.get_session('scraper') as session:
                for i, data in enumerate(competitors_list, 1):
                    try:
                        # Extract domain from URL
                        from urllib.parse import urlparse
                        parsed = urlparse(data['url'])
                        domain = parsed.netloc or parsed.path

                        # Insert query
                        query = """
                        INSERT INTO local_competitors (
                            business_name, url, domain, industry, location,
                            address, phone, priority, tags, notes,
                            is_primary_competitor, competitor_tier,
                            estimated_monthly_traffic, status
                        ) VALUES (
                            :business_name, :url, :domain, :industry, :location,
                            :address, :phone, :priority, :tags, :notes,
                            :is_primary_competitor, :competitor_tier,
                            :estimated_monthly_traffic, :status
                        )
                        ON CONFLICT (url) DO UPDATE SET
                            business_name = EXCLUDED.business_name,
                            industry = COALESCE(EXCLUDED.industry, local_competitors.industry),
                            location = COALESCE(EXCLUDED.location, local_competitors.location),
                            priority = EXCLUDED.priority,
                            modified_date = NOW()
                        RETURNING local_competitor_id
                        """

                        params = {
                            'business_name': data['business_name'],
                            'url': data['url'],
                            'domain': domain,
                            'industry': data.get('industry'),
                            'location': data.get('location'),
                            'address': data.get('address'),
                            'phone': data.get('phone'),
                            'priority': data.get('priority', 5),
                            'tags': data.get('tags', []),
                            'notes': data.get('notes'),
                            'is_primary_competitor': data.get('is_primary_competitor', False),
                            'competitor_tier': data.get('competitor_tier'),
                            'estimated_monthly_traffic': data.get('estimated_monthly_traffic'),
                            'status': data.get('status', 'active')
                        }

                        result = session.execute(text(query), params)
                        competitor_id = result.scalar()

                        if competitor_id:
                            imported_ids.append(competitor_id)
                            success_count += 1

                    except Exception as e:
                        error_count += 1
                        errors.append(f"Row {i}: {str(e)}")
                        logger.error(f"Error importing competitor {i}: {e}")

                # Sync all imported competitors to competitor_urls at once
                if imported_ids:
                    for comp_id in imported_ids:
                        sync_query = "SELECT sync_local_competitor_to_urls(:id)"
                        session.execute(text(sync_query), {'id': comp_id})

                session.commit()

                return {
                    'success': True,
                    'success_count': success_count,
                    'error_count': error_count,
                    'errors': errors,
                    'imported_ids': imported_ids
                }

        except Exception as e:
            logger.error(f"Error in bulk import: {e}")
            return {
                'success': False,
                'error': str(e),
                'success_count': 0,
                'error_count': len(competitors_list)
            }


# Create singleton instance
local_competitors_api = LocalCompetitorsAPI()