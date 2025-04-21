import requests
from bs4 import BeautifulSoup
import logging
import random
import time
from urllib.parse import urljoin

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Base URL
BASE_URL = "https://javtrailers.com"

def get_user_agent():
    """Return a random user agent to avoid detection"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36'
    ]
    return random.choice(user_agents)

def get_session():
    """Create and return a session with headers"""
    session = requests.Session()
    session.headers.update({
        'User-Agent': get_user_agent(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': BASE_URL,
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0',
    })
    return session

def search_actress_videos(actress_name, page=1):
    """
    Search for videos of a specific actress
    
    Args:
        actress_name (str): Name of the actress
        page (int): Page number for pagination
        
    Returns:
        list: List of dictionaries with video info
    """
    logger.debug(f"Searching for actress: {actress_name}, page: {page}")
    
    # Create URL
    url = f"{BASE_URL}/casts/{actress_name}"
    if page > 1:
        url += f"?page={page}"
    
    logger.debug(f"Searching URL: {url}")
    
    try:
        session = get_session()
        response = session.get(url)
        response.raise_for_status()
        
        # Parse the page
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all video containers
        video_containers = soup.select('.item')
        
        if not video_containers:
            logger.warning(f"No videos found for actress: {actress_name} on page {page}")
            return []
        
        videos = []
        for container in video_containers:
            try:
                # Extract video information
                link_element = container.select_one('a')
                title_element = container.select_one('.title')
                thumbnail_element = container.select_one('img.wp-post-image')
                
                if link_element and title_element and thumbnail_element:
                    video_url = urljoin(BASE_URL, link_element['href'])
                    title = title_element.get_text(strip=True)
                    thumbnail_url = thumbnail_element['src']
                    
                    videos.append({
                        'title': title,
                        'url': video_url,
                        'thumbnail': thumbnail_url
                    })
            except Exception as e:
                logger.error(f"Error parsing video container: {str(e)}")
        
        # Check for next page
        pagination = soup.select_one('.pagination')
        has_next_page = pagination and 'Next' in pagination.get_text()
        
        return videos
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        raise Exception(f"Error connecting to JavTrailers: {str(e)}")
    
    except Exception as e:
        logger.error(f"Error searching for actress: {str(e)}")
        raise Exception(f"Error processing search results: {str(e)}")

def get_video_details(video_url):
    """
    Get details for a specific video
    
    Args:
        video_url (str): URL of the video page
        
    Returns:
        dict: Video details including URL, thumbnail, screenshots, and video code
    """
    logger.debug(f"Getting video details from: {video_url}")
    
    try:
        session = get_session()
        response = session.get(video_url)
        response.raise_for_status()
        
        # Parse the page
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Get video code (usually in the title or URL)
        title = soup.select_one('h1').get_text(strip=True) if soup.select_one('h1') else ''
        video_code = ''
        
        # Try to extract code from the title (usually in brackets or at the beginning)
        import re
        code_match = re.search(r'([A-Z0-9]+-[0-9]+)', title)
        if code_match:
            video_code = code_match.group(1)
        else:
            # Try to get from URL
            url_match = re.search(r'/([A-Z0-9]+-[0-9]+)/?', video_url)
            if url_match:
                video_code = url_match.group(1)
            else:
                video_code = "unknown_" + str(int(time.time()))
        
        # Get trailer video URL
        video_element = soup.select_one('video source')
        trailer_url = video_element['src'] if video_element else None
        
        # Get thumbnail
        thumbnail_element = soup.select_one('.wp-post-image')
        thumbnail_url = thumbnail_element['src'] if thumbnail_element else None
        
        # Get screenshots (usually in a gallery or under certain divs)
        screenshots = []
        screenshot_elements = soup.select('.screenshots img, .gallery img, .preview img')
        
        for img in screenshot_elements:
            if 'src' in img.attrs:
                screenshots.append(img['src'])
            elif 'data-src' in img.attrs:
                screenshots.append(img['data-src'])
        
        # Filter out duplicate screenshots
        screenshots = list(set(screenshots))
        
        return {
            'video_code': video_code,
            'title': title,
            'trailer_url': trailer_url,
            'thumbnail_url': thumbnail_url,
            'screenshots': screenshots
        }
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        raise Exception(f"Error connecting to video page: {str(e)}")
    
    except Exception as e:
        logger.error(f"Error getting video details: {str(e)}")
        raise Exception(f"Error processing video details: {str(e)}")
