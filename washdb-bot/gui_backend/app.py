#!/usr/bin/env python3
"""
Washdb-Bot GUI Backend
Flask application for controlling and monitoring the washdb-bot scraper.

This backend is separate from the Nathan SEO Bot dashboard.
Port: 5001 (Nathan SEO Bot uses 5000)
Database: washdb PostgreSQL database only
"""

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import logging
from datetime import datetime

from config import Config
from models.db_manager import DatabaseManager
from api.scraper_routes import scraper_bp
from api.data_routes import data_bp
from api.stats_routes import stats_bp

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Enable CORS for local development
CORS(app)

# Register blueprints (API routes)
app.register_blueprint(scraper_bp, url_prefix='/api/scraper')
app.register_blueprint(data_bp, url_prefix='/api/data')
app.register_blueprint(stats_bp, url_prefix='/api/stats')

# Initialize database manager
db_manager = DatabaseManager(app.config['DATABASE_URL'])

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('../logs/gui_backend.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('index.html')


@app.route('/health')
def health():
    """Health check endpoint."""
    try:
        # Check database connection
        db_status = db_manager.check_connection()

        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'database': 'connected' if db_status else 'disconnected',
            'port': app.config['PORT']
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@app.route('/api/info')
def api_info():
    """API information endpoint."""
    return jsonify({
        'name': 'Washdb-Bot GUI Backend',
        'version': '1.0.0',
        'description': 'Backend API for washdb-bot scraper management',
        'database': 'washdb (PostgreSQL)',
        'port': app.config['PORT'],
        'endpoints': {
            'scraper': '/api/scraper/*',
            'data': '/api/data/*',
            'stats': '/api/stats/*'
        }
    })


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({'error': 'Endpoint not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal error: {error}")
    return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    logger.info("=" * 70)
    logger.info("Starting Washdb-Bot GUI Backend")
    logger.info("=" * 70)
    logger.info(f"Port: {app.config['PORT']}")
    logger.info(f"Database: {app.config['DATABASE_URL'].split('@')[1] if '@' in app.config['DATABASE_URL'] else 'configured'}")
    logger.info(f"Environment: {app.config['ENV']}")
    logger.info("=" * 70)

    app.run(
        host=app.config['HOST'],
        port=app.config['PORT'],
        debug=app.config['DEBUG']
    )
