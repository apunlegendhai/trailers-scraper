import os
import requests
import logging
from pathlib import Path
import time
import random

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def create_directory(directory_path):
    """Create directory if it doesn't exist"""
    try:
        Path(directory_path).mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"Error creating directory {directory_path}: {str(e)}")
        return False

def download_file(url, output_path, session=None):
    """
    Download a file from URL to the specified path
    
    Args:
        url (str): URL of the file to download
        output_path (str): Path where the file should be saved
        session (requests.Session, optional): Session to use for the request
    
    Returns:
        bool: True if download was successful, False otherwise
    """
    if not url:
        logger.warning(f"No URL provided for download to {output_path}")
        return False
    
    # Verify URL format
    if not isinstance(url, str):
        logger.error(f"Invalid URL type for {url}, expected string")
        return False
        
    # Check for relative URLs that need to be converted to absolute
    if url.startswith('/'):
        logger.warning(f"Relative URL detected: {url}, converting to absolute")
        # Convert relative URL to absolute using the base domain
        url = f"https://javtrailers.com{url}"
        
    # Validate URL has proper scheme
    if not url.startswith(('http://', 'https://')):
        logger.error(f"Invalid URL scheme: {url}")
        return False
        
    try:
        # Create session if not provided
        if not session:
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Referer': 'https://javtrailers.com/',
            })
        
        logger.debug(f"Attempting to download from: {url}")
        
        # Add a small delay to avoid being rate-limited
        time.sleep(random.uniform(0.5, 2.0))
        
        # Try alternative URL formats if this is DMM URL
        if 'dmm.co.jp' in url:
            logger.debug(f"DMM URL detected: {url}")
            # We'll let it proceed as is, DMM URLs usually work well
        
        # Add more headers for video requests
        if url.endswith('.mp4'):
            session.headers.update({
                'Accept': '*/*',
                'Accept-Encoding': 'identity;q=1, *;q=0',
                'Accept-Language': 'en-US,en;q=0.9',
                'Range': 'bytes=0-',
            })

        # Stream the download to handle large files
        with session.get(url, stream=True, allow_redirects=True, timeout=30) as response:
            response.raise_for_status()
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Check content type and size
            content_type = response.headers.get('Content-Type', '')
            content_length = int(response.headers.get('Content-Length', 0))
            
            if content_length == 0:
                logger.error(f"Empty content received from {url}")
                return False
                
            if url.endswith('.mp4') and 'video' not in content_type.lower():
                logger.warning(f"Expected video content but got {content_type} from {url}")
            
            # Check if response is valid by looking at content type
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' in content_type and not url.endswith(('.mp4', '.jpg', '.jpeg', '.png', '.gif')):
                logger.warning(f"Expected file but got HTML response from {url}")
                
                # Try to find a direct download link in the HTML response
                try:
                    import re
                    from bs4 import BeautifulSoup
                    
                    html_content = response.text
                    soup = BeautifulSoup(html_content, 'html.parser')
                    
                    # Look for video tags or source tags
                    video_src = None
                    video_tags = soup.select('video source[src], source[src], video[src]')
                    
                    for tag in video_tags:
                        if tag.has_attr('src'):
                            src_value = tag.get('src')
                            if isinstance(src_value, str) and src_value.endswith('.mp4'):
                                video_src = src_value
                                break
                            
                    if video_src:
                        logger.info(f"Found direct media link in HTML: {video_src}")
                        # Create a new request for the actual file
                        return download_file(video_src, output_path, session)
                        
                    # If we can't find a direct link, we'll fall back to saving the HTML response
                    logger.warning("Could not find direct media link in HTML, falling back to saving HTML content")
                except Exception as e:
                    logger.error(f"Error parsing HTML response: {str(e)}")
            
            # If we got here, we're going to save whatever content was returned
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        
        logger.debug(f"Downloaded {url} to {output_path}")
        return True
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Error downloading {url}: {str(e)}")
        return False
    
    except Exception as e:
        logger.error(f"Error saving file to {output_path}: {str(e)}")
        return False

def download_assets(video_details, actress_name, video_code):
    """
    Download all assets for a video
    
    Args:
        video_details (dict): Dictionary with video details
        actress_name (str): Sanitized actress name
        video_code (str): Video code for folder organization
    
    Returns:
        dict: Summary of download results
    """
    logger.debug(f"Downloading assets for {video_code}")
    
    # Create base directory structure
    base_dir = os.path.join("downloads", actress_name, video_code)
    create_directory(base_dir)
    
    # Create session for downloads
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://javtrailers.com/',
    })
    
    results = {
        'trailer': False,
        'thumbnail': False,
        'screenshots': []
    }
    
    # Download trailer
    if video_details.get('trailer_url'):
        trailer_path = os.path.join(base_dir, f"{video_code}_trailer.mp4")
        results['trailer'] = download_file(video_details['trailer_url'], trailer_path, session)
    
    # Download thumbnail
    if video_details.get('thumbnail_url'):
        # Check if the thumbnail URL is a default/fallback image 
        # and don't try to download it if it's the placeholder
        if 'no-image.jpg' not in video_details['thumbnail_url']:
            thumbnail_path = os.path.join(base_dir, f"{video_code}_thumbnail.jpg")
            results['thumbnail'] = download_file(video_details['thumbnail_url'], thumbnail_path, session)
        else:
            logger.warning(f"Skipping default thumbnail image for {video_code}")
            results['thumbnail'] = False
    
    # Download screenshots
    screenshots_dir = os.path.join(base_dir, "screenshots")
    create_directory(screenshots_dir)
    
    for i, screenshot_url in enumerate(video_details.get('screenshots', [])):
        screenshot_path = os.path.join(screenshots_dir, f"{video_code}_screenshot_{i+1}.jpg")
        success = download_file(screenshot_url, screenshot_path, session)
        results['screenshots'].append({
            'url': screenshot_url,
            'success': success,
            'path': screenshot_path if success else None
        })
    
    # Summary
    results['summary'] = {
        'actress': actress_name,
        'video_code': video_code,
        'directory': base_dir,
        'total_screenshots': len(video_details.get('screenshots', [])),
        'successful_screenshots': sum(1 for s in results['screenshots'] if s['success'])
    }
    
    logger.debug(f"Download summary: {results['summary']}")
    return results
