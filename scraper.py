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

def extract_nuxt_data(soup):
    """
    Extract Nuxt.js data from soup object
    
    Args:
        soup (BeautifulSoup): Parsed HTML
        
    Returns:
        dict or None: Parsed Nuxt data or None if not found/valid
    """
    scripts = soup.find_all('script')
    for script in scripts:
        script_text = script.string
        if script_text and 'window.__NUXT__=' in script_text:
            logger.debug("Found Nuxt data in page")
            try:
                # Extract the JSON part from the script
                import re
                import json
                
                # Extract the JSON part
                json_match = re.search(r'window\.__NUXT__\s*=\s*(.*?)(;</script>|$)', script_text, re.DOTALL)
                if json_match:
                    try:
                        # Clean and parse the JSON
                        json_data = json_match.group(1).strip()
                        while json_data and not json_data[-1] in ']}":0123456789':
                            json_data = json_data[:-1]
                            
                        return json.loads(json_data)
                    except json.JSONDecodeError as e:
                        logger.error(f"Error parsing Nuxt JSON: {str(e)}")
            except Exception as e:
                logger.error(f"Error extracting Nuxt data: {str(e)}")
    return None

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
        
        # Get trailer video URL - first try to find it in JavaScript data
        trailer_url = None
        nuxt_data = None  # Initialize nuxt_data for later use
        
        # Try to extract from Nuxt data first (most reliable)
        scripts = soup.find_all('script')
        for script in scripts:
            script_text = script.string
            if script_text and 'window.__NUXT__=' in script_text:
                logger.debug("Found Nuxt data in video page, attempting to extract trailer URL")
                try:
                    # Extract the JSON part from the script
                    import re
                    import json
                    
                    # Extract the JSON part
                    json_match = re.search(r'window\.__NUXT__\s*=\s*(.*?)(;</script>|$)', script_text, re.DOTALL)
                    if json_match:
                        try:
                            # Clean and parse the JSON
                            json_data = json_match.group(1).strip()
                            while json_data and not json_data[-1] in ']}":0123456789':
                                json_data = json_data[:-1]
                                
                            nuxt_data = json.loads(json_data)
                            
                            # Look for video data in different possible locations
                            if 'state' in nuxt_data and isinstance(nuxt_data['state'], dict):
                                state = nuxt_data['state']
                                
                                # Try to get from videos state
                                if 'video' in state and 'trailer' in state['video']:
                                    trailer_url = state['video']['trailer']
                                    logger.debug(f"Found trailer URL in Nuxt data: {trailer_url}")
                                
                                # Another possible location
                                elif 'videos' in state and 'current' in state['videos']:
                                    current = state['videos']['current']
                                    if 'trailer' in current:
                                        trailer_url = current['trailer']
                                        logger.debug(f"Found trailer URL in Nuxt videos.current: {trailer_url}")
                        
                        except json.JSONDecodeError as e:
                            logger.error(f"Error parsing Nuxt JSON in video page: {str(e)}")
                except Exception as e:
                    logger.error(f"Error extracting trailer from Nuxt data: {str(e)}")
        
        # If we still don't have a trailer URL, try direct HTML elements
        if not trailer_url:
            # Try multiple selectors that might contain the video
            video_elements = soup.select('video source[src], source[src], video[src], iframe[src], a[href$=".mp4"]')
            for video_element in video_elements:
                if 'src' in video_element.attrs:
                    src = video_element['src']
                    # Check if it looks like a video URL
                    if isinstance(src, str) and (src.endswith('.mp4') or '.mp4?' in src or 'video' in src):
                        trailer_url = src
                        logger.debug(f"Found trailer URL in HTML: {trailer_url}")
                        break
                elif 'href' in video_element.attrs:
                    href = video_element['href']
                    if isinstance(href, str) and href.endswith('.mp4'):
                        trailer_url = href
                        logger.debug(f"Found trailer URL in href: {trailer_url}")
                        break
                    
        # If still no trailer, check for embedded players
        if not trailer_url:
            iframes = soup.select('iframe')
            for iframe in iframes:
                if 'src' in iframe.attrs:
                    src = iframe.attrs['src']
                    if 'player' in src or 'embed' in src or 'video' in src:
                        # This is likely a video player iframe
                        iframe_src = iframe.attrs['src']
                        logger.debug(f"Found potential iframe video source: {iframe_src}")
                        # Follow the iframe source
                        try:
                            iframe_response = session.get(iframe_src)
                            iframe_response.raise_for_status()
                            
                            iframe_soup = BeautifulSoup(iframe_response.text, 'html.parser')
                            iframe_video = iframe_soup.select_one('video source[src], source[src]')
                            if iframe_video and 'src' in iframe_video.attrs:
                                trailer_url = iframe_video['src']
                                logger.debug(f"Found trailer URL in iframe: {trailer_url}")
                                break
                        except Exception as e:
                            logger.error(f"Error following iframe: {str(e)}")
                                
        # As a last resort, look for a URL pattern in the page text that might be the video
        if not trailer_url:
            try:
                video_pattern = re.search(r'(https?://[^"\s]+\.mp4[^"\s]*)', str(soup))
                if video_pattern:
                    trailer_url = video_pattern.group(1)
                    logger.debug(f"Found trailer URL using regex: {trailer_url}")
            except Exception as e:
                logger.error(f"Error finding video with regex: {str(e)}")
                
        # Log the outcome
        if trailer_url:
            logger.debug(f"Successfully found trailer URL: {trailer_url}")
        else:
            logger.warning(f"No trailer URL found for {video_url}")
        
        # Get thumbnail - first try to extract from Nuxt data
        thumbnail_url = None
        
        # Try to find in Nuxt data first if it was successfully extracted
        if nuxt_data is not None and 'state' in nuxt_data and isinstance(nuxt_data['state'], dict):
            state = nuxt_data['state']
            
            # Possible thumbnail locations
            if 'video' in state and 'thumb' in state['video']:
                thumbnail_url = state['video']['thumb']
                logger.debug(f"Found thumbnail URL in Nuxt data: {thumbnail_url}")
            elif 'videos' in state and 'current' in state['videos'] and 'thumb' in state['videos']['current']:
                thumbnail_url = state['videos']['current']['thumb']
                logger.debug(f"Found thumbnail URL in Nuxt videos.current: {thumbnail_url}")
        
        # If not found in Nuxt data, try selectors
        if not thumbnail_url:
            # Try multiple selectors for thumbnails
            thumbnail_selectors = [
                '.wp-post-image', '.poster img', '.thumbnail img', '.cover img', 
                '.featured-image img', 'img.cover', 'img.poster', 
                '.video-image', '.movie-image', '.main-image',
                '.card-image', '.image img', '.preview-image'
            ]
            
            for selector in thumbnail_selectors:
                thumbnail_element = soup.select_one(selector)
                if thumbnail_element and 'src' in thumbnail_element.attrs:
                    thumbnail_url = thumbnail_element['src']
                    logger.debug(f"Found thumbnail URL using selector {selector}: {thumbnail_url}")
                    break
        
        # If still no thumbnail, try to construct one from the video code
        if not thumbnail_url and video_code:
            # Try a few common patterns for thumbnail URLs
            potential_urls = [
                f"https://javtrailers.com/thumbs/{video_code.lower()}.jpg",
                f"https://javtrailers.com/images/{video_code.lower()}.jpg",
                f"https://javtrailers.com/covers/{video_code.lower()}.jpg"
            ]
            
            for potential_url in potential_urls:
                try:
                    # Check if URL exists
                    head_response = session.head(potential_url)
                    if head_response.status_code == 200:
                        thumbnail_url = potential_url
                        logger.debug(f"Found thumbnail using constructed URL: {thumbnail_url}")
                        break
                except Exception:
                    continue
        
        # Log the outcome
        if thumbnail_url:
            logger.debug(f"Successfully found thumbnail URL: {thumbnail_url}")
        else:
            logger.warning(f"No thumbnail URL found for {video_code}")
            # Use a default thumbnail as last resort
            thumbnail_url = "https://javtrailers.com/images/no-image.jpg"
        
        # Get screenshots (usually in a gallery or under certain divs)
        screenshots = []
        
        # Try multiple selectors that could contain screenshots
        screenshot_elements = soup.select('.screenshots img, .gallery img, .preview img, .sample-images img, .movie-samples img, .movie-gallery img, .samples-list img, .thumbs img')
        
        if not screenshot_elements:
            # If no dedicated screenshot containers found, look for all images
            screenshot_elements = soup.select('img')
            
            # Filter out the thumbnail if we have one
            if thumbnail_url:
                # Create a new list excluding the thumbnail
                filtered_elements = []
                for img in screenshot_elements:
                    if 'src' in img.attrs and img['src'] != thumbnail_url:
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
