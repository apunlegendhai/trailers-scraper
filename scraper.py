import requests
from bs4 import BeautifulSoup
import logging
import random
import time
from urllib.parse import urljoin, urlparse, quote, urlunparse
from typing import Optional, Union, cast

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
    
    # Format the name for URL: convert spaces to dashes, lowercase
    formatted_name = actress_name.lower().replace(' ', '-')
    
    # Create the URL using the format provided - casts/actress-name
    url = f"{BASE_URL}/casts/{formatted_name}"
    if page > 1:
        url += f"?page={page}"
    
    logger.debug(f"Searching URL: {url}")
    
    try:
        session = get_session()
        response = session.get(url)
        response.raise_for_status()
        
        # Parse the page
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Initialize videos list
        videos = []
        
        # First try to get data directly from the Nuxt.js data in JavaScript
        scripts = soup.find_all('script')
        nuxt_data_found = False
        
        for script in scripts:
            script_text = script.string
            if script_text and 'window.__NUXT__=' in script_text:
                logger.debug("Found Nuxt data in script, attempting to extract")
                try:
                    # Extract the JSON part from the script
                    import re
                    import json
                    
                    # Extract the JSON part from the script
                    json_match = re.search(r'window\.__NUXT__\s*=\s*(.*?)(;</script>|$)', script_text, re.DOTALL)
                    if json_match:
                        try:
                            # Try to clean and parse the JSON
                            json_data = json_match.group(1).strip()
                            # Remove trailing semicolons or other invalid JSON parts
                            while json_data and not json_data[-1] in ']}":0123456789':
                                json_data = json_data[:-1]
                                
                            nuxt_data = json.loads(json_data)
                            nuxt_data_found = True
                            logger.debug("Successfully parsed Nuxt data")
                            
                            # Attempt to extract video data from the expected structure
                            if 'state' in nuxt_data and isinstance(nuxt_data['state'], dict):
                                state = nuxt_data['state']
                                # Look for different possible video data locations
                                if 'videos' in state and 'items' in state['videos']:
                                    items = state['videos']['items']
                                    logger.debug(f"Found items in Nuxt data: {len(items)}")
                                    
                                    for key, video_data in items.items():
                                        if isinstance(video_data, dict):
                                            try:
                                                title = video_data.get('title', '')
                                                code = video_data.get('code', '').lower()
                                                video_url = f"{BASE_URL}/video/{code}"
                                                thumbnail = video_data.get('thumb', '')
                                                
                                                videos.append({
                                                    'title': title,
                                                    'url': video_url,
                                                    'thumbnail': thumbnail
                                                })
                                                logger.debug(f"Added video from Nuxt data: {title}")
                                            except Exception as e:
                                                logger.error(f"Error extracting video item: {str(e)}")
                        except json.JSONDecodeError as e:
                            logger.error(f"Error parsing Nuxt JSON: {str(e)}")
                except Exception as e:
                    logger.error(f"Error processing Nuxt data: {str(e)}")
        
        # If we successfully found videos from the Nuxt data, return them
        if videos:
            logger.debug(f"Returning {len(videos)} videos from Nuxt data")
            return videos
        
        # If no videos from Nuxt data, try DOM-based approach
        logger.debug("No videos from Nuxt data, trying DOM approach")
        
        # Find containers with the observed classes from debugging
        card_containers = soup.select('.card-container')
        video_cards = soup.select('.video-card')
        
        logger.debug(f"Found {len(card_containers)} card-container elements")
        logger.debug(f"Found {len(video_cards)} video-card elements")
        
        # Use card containers as they're more likely to contain the videos
        for container in card_containers:
            try:
                # Extract elements from container
                link_element = container.select_one('a')
                title_element = container.select_one('.title')
                
                # Try multiple selectors for thumbnail
                thumbnail_element = container.select_one('img.video-image, img, a > img')
                
                # Debug found elements 
                if link_element:
                    logger.debug(f"Found link: {link_element['href'] if 'href' in link_element.attrs else 'No href'}")
                if title_element:
                    logger.debug(f"Found title: {title_element.get_text(strip=True) if title_element else 'No title'}")
                if thumbnail_element:
                    logger.debug(f"Found thumbnail: {thumbnail_element['src'] if 'src' in thumbnail_element.attrs else 'No src'}")
                
                # If we have link and title, that's enough to extract useful data
                # We can use a default thumbnail if one isn't found
                if (link_element and 'href' in link_element.attrs and title_element):
                    
                    # Get href as string
                    href = str(link_element['href'])
                    
                    # Create full URL
                    if href.startswith('/'):
                        video_url = f"{BASE_URL}{href}"
                    elif href.startswith('http'):
                        video_url = href
                    else:
                        video_url = f"{BASE_URL}/{href}"
                    
                    # Extract title and thumbnail
                    title = title_element.get_text(strip=True)
                    
                    # Get thumbnail URL if available, or use a default
                    thumbnail_url = None
                    if thumbnail_element and 'src' in thumbnail_element.attrs:
                        thumbnail_url = thumbnail_element['src']
                    else:
                        # Extract code from URL for potential thumbnail
                        import re
                        code_match = re.search(r'/video/([a-z0-9]+)/?$', video_url)
                        if code_match:
                            video_code = code_match.group(1)
                            # Use a code-based URL that might work as thumbnail
                            thumbnail_url = f"{BASE_URL}/thumbs/{video_code}.jpg"
                        else:
                            # Use a default placeholder
                            thumbnail_url = f"{BASE_URL}/images/no-preview.jpg"
                    
                    # Add to results
                    videos.append({
                        'title': title,
                        'url': video_url,
                        'thumbnail': thumbnail_url
                    })
            except Exception as e:
                logger.error(f"Error parsing container: {str(e)}")
        
        # Check for pagination
        pagination = soup.select_one('.pagination')
        has_next_page = False
        if pagination:
            next_link = pagination.select_one('a:contains("Next")')
            has_next_page = next_link is not None
        
        if not videos:
            logger.warning(f"No videos found for actress: {actress_name} on page {page}")
        
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
        # Make sure the URL is properly encoded
        from urllib.parse import urlparse, quote, urlunparse
        parsed_url = urlparse(video_url)
        # Ensure the path is properly encoded
        encoded_path = quote(parsed_url.path)
        # Rebuild the URL with the encoded path
        encoded_url = urlunparse((
            parsed_url.scheme, 
            parsed_url.netloc, 
            encoded_path,
            parsed_url.params, 
            parsed_url.query, 
            parsed_url.fragment
        ))
        
        session = get_session()
        response = session.get(encoded_url)
        response.raise_for_status()
        
        # Parse the page
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Get video code (usually in the title or URL)
        title_element = soup.select_one('h1, .title, .movie-title')
        title = title_element.get_text(strip=True) if title_element else ''
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
                # Final fallback
                video_code = "unknown_" + str(int(time.time()))
        
        # Get trailer video URL - try multiple selectors
        video_element = soup.select_one('video source, source[src], video[src], iframe[src]')
        trailer_url = None
        if video_element and 'src' in video_element.attrs:
            trailer_url = video_element['src']
        
        # Get thumbnail - try multiple selectors
        thumbnail_element = soup.select_one('.wp-post-image, .poster img, .thumbnail img, .cover img, .featured-image img, img.cover, img.poster')
        thumbnail_url = thumbnail_element['src'] if thumbnail_element and 'src' in thumbnail_element.attrs else None
        
        # Get screenshots (usually in a gallery or under certain divs)
        screenshots = []
        
        # Try multiple selectors that could contain screenshots
        screenshot_elements = soup.select('.screenshots img, .gallery img, .preview img, .sample-images img, .movie-samples img, .movie-gallery img, .samples-list img, .thumbs img')
        
        if not screenshot_elements:
            # If no dedicated screenshot containers found, look for all images
            screenshot_elements = soup.select('img')
            
            # Filter out the thumbnail if we know what it is
            if thumbnail_element and 'src' in thumbnail_element.attrs:
                thumbnail_src = thumbnail_element['src']
                # Create a new list excluding the thumbnail
                filtered_elements = []
                for img in screenshot_elements:
                    if 'src' in img.attrs and img['src'] != thumbnail_src:
                        filtered_elements.append(img)
                screenshot_elements = filtered_elements
            
        for img in screenshot_elements:
            # Check different possible image attributes
            if 'src' in img.attrs:
                screenshots.append(img['src'])
            elif 'data-src' in img.attrs:
                screenshots.append(img['data-src'])
            elif 'data-original' in img.attrs:
                screenshots.append(img['data-original'])
            elif 'data-lazy-src' in img.attrs:
                screenshots.append(img['data-lazy-src'])
        
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
