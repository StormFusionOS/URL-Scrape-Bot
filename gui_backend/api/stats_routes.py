"""
Statistics API Routes

Endpoints for viewing scraper statistics and metrics.
"""

from flask import Blueprint, jsonify, current_app
import logging

stats_bp = Blueprint('stats', __name__)
logger = logging.getLogger(__name__)


@stats_bp.route('/overview', methods=['GET'])
def get_overview():
    """
    Get overview statistics.

    Returns:
        JSON with key statistics
    """
    try:
        from models.db_manager import DatabaseManager
        db_manager = DatabaseManager(current_app.config['DATABASE_URL'])

        stats = db_manager.get_stats()

        return jsonify({
            'stats': stats,
            'timestamp': None  # TODO: Add timestamp
        })
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return jsonify({'error': str(e)}), 500


@stats_bp.route('/recent-activity', methods=['GET'])
def get_recent_activity():
    """
    Get recent scraping activity.

    Returns:
        JSON with recent activity
    """
    # TODO: Implement recent activity tracking

    return jsonify({
        'recent_scrapes': [],
        'message': 'Recent activity tracking not yet implemented'
    })


@stats_bp.route('/performance', methods=['GET'])
def get_performance():
    """
    Get performance metrics.

    Returns:
        JSON with performance data
    """
    # TODO: Implement performance metrics

    return jsonify({
        'avg_scrape_time': None,
        'success_rate': None,
        'message': 'Performance metrics not yet implemented'
    })


@stats_bp.route('/database', methods=['GET'])
def get_database_stats():
    """
    Get database statistics.

    Returns:
        JSON with database stats
    """
    try:
        from models.db_manager import DatabaseManager
        db_manager = DatabaseManager(current_app.config['DATABASE_URL'])

        # Get database size info (if available)
        stats = {
            'connection_status': 'connected' if db_manager.check_connection() else 'disconnected',
            'tables': {
                'companies': db_manager.get_company_count(),
                'discovery_runs': len(db_manager.get_discovery_runs(limit=1000))
            }
        }

        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error fetching database stats: {e}")
        return jsonify({'error': str(e)}), 500
