"""
Data Access API Routes

Endpoints for accessing scraped data from washdb database.
"""

from flask import Blueprint, jsonify, request, current_app
import logging

data_bp = Blueprint('data', __name__)
logger = logging.getLogger(__name__)


@data_bp.route('/companies', methods=['GET'])
def get_companies():
    """
    Get list of companies from database.

    Query params:
        page: Page number (default: 1)
        per_page: Items per page (default: 50, max: 1000)
        has_website: Filter by website presence (optional)
        has_phone: Filter by phone presence (optional)

    Returns:
        JSON with companies list and pagination info
    """
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 1000)

    # Build filters
    filters = {}
    if request.args.get('has_website'):
        filters['has_website'] = True
    if request.args.get('has_phone'):
        filters['has_phone'] = True

    # Calculate offset
    offset = (page - 1) * per_page

    try:
        # Get database manager from app context
        from models.db_manager import DatabaseManager
        db_manager = DatabaseManager(current_app.config['DATABASE_URL'])

        # Fetch companies
        companies = db_manager.get_companies(limit=per_page, offset=offset, filters=filters)
        total = db_manager.get_company_count(filters=filters)

        return jsonify({
            'companies': companies,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        })
    except Exception as e:
        logger.error(f"Error fetching companies: {e}")
        return jsonify({'error': str(e)}), 500


@data_bp.route('/companies/<int:company_id>', methods=['GET'])
def get_company(company_id):
    """
    Get single company by ID.

    Args:
        company_id: Company ID

    Returns:
        JSON with company details
    """
    # TODO: Implement single company fetch

    return jsonify({
        'id': company_id,
        'message': 'Single company fetch not yet implemented'
    })


@data_bp.route('/discovery-runs', methods=['GET'])
def get_discovery_runs():
    """
    Get list of discovery runs.

    Query params:
        limit: Number of runs to return (default: 20)

    Returns:
        JSON with discovery runs
    """
    limit = request.args.get('limit', 20, type=int)

    try:
        from models.db_manager import DatabaseManager
        db_manager = DatabaseManager(current_app.config['DATABASE_URL'])

        runs = db_manager.get_discovery_runs(limit=limit)

        return jsonify({
            'discovery_runs': runs,
            'total': len(runs)
        })
    except Exception as e:
        logger.error(f"Error fetching discovery runs: {e}")
        return jsonify({'error': str(e)}), 500


@data_bp.route('/export', methods=['POST'])
def export_data():
    """
    Export data to CSV/JSON.

    Request body:
        {
            "format": "csv" | "json",
            "filters": {...}
        }

    Returns:
        File download or JSON with export status
    """
    data = request.get_json()
    export_format = data.get('format', 'csv')

    logger.info(f"Data export requested in format: {export_format}")

    # TODO: Implement data export

    return jsonify({
        'status': 'success',
        'message': f'Export in {export_format} format',
        'note': 'Export functionality not yet implemented'
    })
