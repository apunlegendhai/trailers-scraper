import os
import logging
from flask import Flask, render_template, request, jsonify
from scraper import search_actress_videos, get_video_details
from downloader import download_assets
from utils import sanitize_filename

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev_secret_key")

@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    """Search for videos based on actress name"""
    data = request.json
    actress_name = data.get('actress_name', '')
    page = data.get('page', 1)
    
    if not actress_name:
        return jsonify({'success': False, 'error': 'Actress name is required'}), 400
    
    try:
        videos = search_actress_videos(actress_name, page)
        return jsonify({'success': True, 'videos': videos, 'page': page})
    except Exception as e:
        logger.error(f"Error searching videos: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download():
    """Download video assets"""
    data = request.json
    video_url = data.get('video_url', '')
    actress_name = data.get('actress_name', '')
    
    if not video_url or not actress_name:
        return jsonify({'success': False, 'error': 'Video URL and actress name are required'}), 400
    
    try:
        # Get video details first
        video_details = get_video_details(video_url)
        
        # Download the assets
        actress_name_sanitized = sanitize_filename(actress_name)
        video_code = video_details.get('video_code', 'unknown')
        
        download_result = download_assets(
            video_details, 
            actress_name_sanitized, 
            video_code
        )
        
        return jsonify({
            'success': True, 
            'message': 'Download completed successfully',
            'details': download_result
        })
    except Exception as e:
        logger.error(f"Error downloading video: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/download_random', methods=['POST'])
def download_random():
    """Download a random video for the actress"""
    data = request.json
    actress_name = data.get('actress_name', '')
    
    if not actress_name:
        return jsonify({'success': False, 'error': 'Actress name is required'}), 400
    
    try:
        # Search for videos
        videos = search_actress_videos(actress_name, 1)
        
        if not videos:
            return jsonify({'success': False, 'error': 'No videos found for this actress'}), 404
        
        # Select a random video
        import random
        random_video = random.choice(videos)
        
        # Get video details
        video_details = get_video_details(random_video['url'])
        
        # Download the assets
        actress_name_sanitized = sanitize_filename(actress_name)
        video_code = video_details.get('video_code', 'unknown')
        
        download_result = download_assets(
            video_details, 
            actress_name_sanitized, 
            video_code
        )
        
        return jsonify({
            'success': True, 
            'message': 'Random video download completed successfully',
            'video_title': random_video['title'],
            'details': download_result
        })
    except Exception as e:
        logger.error(f"Error downloading random video: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.errorhandler(404)
def page_not_found(e):
    return render_template('index.html'), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500
