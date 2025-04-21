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
        
        # Extract Nuxt data - most reliable source of information
        nuxt_data = extract_nuxt_data(soup)
        
        # Get trailer video URL - first try to find it in the Nuxt data
        trailer_url = None
        
        # If we have Nuxt data, try to extract the trailer URL from it
        if nuxt_data and isinstance(nuxt_data, dict) and 'state' in nuxt_data:
            state = nuxt_data['state']
            
            # The trailer URL might be in several different locations
            if 'video' in state and isinstance(state['video'], dict):
                # Try video.trailer
                if 'trailer' in state['video'] and state['video']['trailer']:
                    trailer_url = state['video']['trailer']
                    logger.debug(f"Found trailer URL in state.video.trailer: {trailer_url}")
                # Try video.trailerUrl
                elif 'trailerUrl' in state['video'] and state['video']['trailerUrl']:
                    trailer_url = state['video']['trailerUrl']
                    logger.debug(f"Found trailer URL in state.video.trailerUrl: {trailer_url}")
                # Try video.movieurl
                elif 'movieurl' in state['video'] and state['video']['movieurl']:
                    trailer_url = state['video']['movieurl']
                    logger.debug(f"Found trailer URL in state.video.movieurl: {trailer_url}")
            
            # Check videos.current if available
            if not trailer_url and 'videos' in state and 'current' in state['videos']:
                current = state['videos']['current']
                if isinstance(current, dict):
                    # Check different possible keys
                    for key in ['trailer', 'trailerUrl', 'movieurl', 'video', 'url']:
                        if key in current and current[key]:
                            trailer_url = current[key]
                            logger.debug(f"Found trailer URL in videos.current.{key}: {trailer_url}")
                            break
        
        # If still no trailer URL, check for video elements in the HTML
        if not trailer_url:
            logger.debug("No trailer URL in Nuxt data, searching HTML elements")
            
            # Find video elements
            video_tags = soup.select('video')
            for video in video_tags:
                # Check for source tags inside
                sources = video.select('source')
                for source in sources:
                    if 'src' in source.attrs:
                        src = source['src']
                        if isinstance(src, str) and (src.endswith('.mp4') or '.mp4?' in src):
                            trailer_url = src
                            logger.debug(f"Found trailer URL in video source: {trailer_url}")
                            break
                
                # Check for src directly on video element
                if not trailer_url and 'src' in video.attrs:
                    src = video['src']
                    if isinstance(src, str) and (src.endswith('.mp4') or '.mp4?' in src):
                        trailer_url = src
                        logger.debug(f"Found trailer URL in video src: {trailer_url}")
                
                if trailer_url:
                    break
            
            # If still no trailer, try other elements
            if not trailer_url:
                # Try to find links ending with .mp4
                mp4_links = soup.select('a[href$=".mp4"]')
                for link in mp4_links:
                    trailer_url = link['href']
                    logger.debug(f"Found trailer URL in link: {trailer_url}")
                    break
                
                # Try iframes that might embed players
                if not trailer_url:
                    # Find all iframes with src attribute
                    iframes = soup.select('iframe')
                    
                    for iframe in iframes:
                        # Check if iframe has src attribute
                        if not iframe.has_attr('src'):
                            continue
                            
                        # Get src value
                        src = iframe['src']
                        
                        # Verify src is a string
                        if not isinstance(src, str):
                            continue
                            
                        # Check if it's likely a video player
                        if not ('player' in src or 'video' in src or 'embed' in src):
                            continue
                            
                        logger.debug(f"Found potential iframe video source: {src}")
                        
                        # Try to follow the iframe
                        try:
                            # Make request to iframe src
                            iframe_response = session.get(src)
                            iframe_response.raise_for_status()
                            
                            # Parse iframe content
                            iframe_soup = BeautifulSoup(iframe_response.text, 'html.parser')
                            
                            # Look for video sources
                            sources = iframe_soup.select('source')
                            
                            # Check each source for mp4 content
                            for source in sources:
                                if source.has_attr('src'):
                                    source_src = source['src']
                                    if isinstance(source_src, str) and source_src.endswith('.mp4'):
                                        trailer_url = source_src
                                        logger.debug(f"Found trailer URL in iframe: {trailer_url}")
                                        break
                                        
                            # Break outer loop if trailer found
                            if trailer_url:
                                break
                                
                        except Exception as e:
                            logger.error(f"Error checking iframe {src}: {str(e)}")
                    
        # Previous iframe check already done, no need to duplicate
                                
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
        
        # Get screenshots/preview images specific to this video
        screenshots = []
        
        # First try to extract screenshots from Nuxt data
        if nuxt_data and 'state' in nuxt_data:
            state = nuxt_data['state']
            
            # Check for various paths where screenshots might be stored
            if 'video' in state and isinstance(state['video'], dict):
                # Look for samples, screenshots, or images array
                for key in ['samples', 'screenshots', 'images', 'preview', 'previews']:
                    if key in state['video'] and isinstance(state['video'][key], list):
                        for img_url in state['video'][key]:
                            if isinstance(img_url, str) and img_url:
                                screenshots.append(img_url)
                                logger.debug(f"Found screenshot in Nuxt data: {img_url}")
            
            # Check videos.current if available
            if 'videos' in state and 'current' in state['videos']:
                current = state['videos']['current']
                if isinstance(current, dict):
                    # Check for various keys with screenshots
                    for key in ['samples', 'screenshots', 'images', 'preview', 'previews']:
                        if key in current and isinstance(current[key], list):
                            for img_url in current[key]:
                                if isinstance(img_url, str) and img_url:
                                    screenshots.append(img_url)
                                    logger.debug(f"Found screenshot in videos.current: {img_url}")
        
        # If no screenshots found in Nuxt data, try HTML
        if not screenshots:
            logger.debug("No screenshots found in Nuxt data, searching HTML")
            
            # Look for elements in specific containers likely to hold screenshots
            containers = soup.select('.screenshots, .gallery, .preview, .sample-images, .movie-samples, .movie-gallery, .samples-list, .thumbs')
            
            for container in containers:
                # Get all images within these containers
                img_elements = container.select('img[src]')
                for img in img_elements:
                    if 'src' in img.attrs and img['src']:
                        screenshots.append(img['src'])
                        logger.debug(f"Found screenshot in container: {img['src']}")
            
            # If still no screenshots, look for images matching certain patterns in URL
            if not screenshots:
                img_elements = soup.select('img[src]')
                
                # Filter for images that are likely screenshots/samples
                # based on their URL patterns
                for img in img_elements:
                    src = img['src']
                    # Skip the thumbnail
                    if thumbnail_url and src == thumbnail_url:
                        continue
                    
                    # Check for common screenshot URL patterns
                    src_lower = src.lower() if isinstance(src, str) else ""
                    if any(pattern in src_lower for pattern in 
                          ['sample', 'preview', 'screenshot', 'gallery', 'thumb', 
                           'cap', 'snap', 'still']):
                        screenshots.append(src)
                        logger.debug(f"Found screenshot from pattern match: {src}")
        
        # Filter out duplicates
        screenshots = list(set(screenshots))
        
        # Filter out any tiny images or icons
        filtered_screenshots = []
        for src in screenshots:
            # Ensure src is a string before checking
            if not isinstance(src, str):
                continue
                
            # Skip URLs that look like icons or logos
            if any(pattern in src.lower() for pattern in ['icon', 'logo', 'favicon']):
                continue
            
            # Add to filtered list
            filtered_screenshots.append(src)
        
        # Update the list
        screenshots = filtered_screenshots
        
        # Limit to a reasonable number of screenshots (max 10)
        if len(screenshots) > 10:
            screenshots = screenshots[:10]
            
        logger.debug(f"Found {len(screenshots)} screenshot images for {video_code}")
        
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
