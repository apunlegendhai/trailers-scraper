import os
import random
import re
import string
import time
import logging
import requests
import subprocess
import mimetypes
import json
import datetime
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from yt_dlp import YoutubeDL
from contextlib import contextmanager

# Constants
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)" \
             " Chrome/114.0.0.0 Safari/537.36"
BASE_URL = "https://javtrailers.com"
CASTS_URL = urljoin(BASE_URL, "/casts")
DOWNLOAD_DIR = "downloads"
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "scraper.log")

MAX_RETRIES = 5
RETRY_BACKOFF_FACTOR = 2  # exponential backoff multiplier
PAGE_LOAD_TIMEOUT = 15  # seconds
VIDEO_RATE_LIMIT = "500K"  # yt_dlp rate limit
VIDEO_RETRY_COUNT = 3

# Setup logging
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@contextmanager
def wait_for_page_load(driver, timeout=PAGE_LOAD_TIMEOUT):
    """Context manager to wait for page load to complete."""
    old_page = driver.find_element(By.TAG_NAME, 'html')
    yield
    WebDriverWait(driver, timeout).until(
        EC.staleness_of(old_page)
    )

def init_driver():
    """Initialize headless Chrome WebDriver with anti-bot evasion."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument(f"user-agent={USER_AGENT}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)

    # Anti-detection scripts
    driver.execute_cdp_cmd(
        'Page.addScriptToEvaluateOnNewDocument',
        {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.navigator.chrome = {
                    runtime: {}
                };
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
            '''
        }
    )
    
    # Navigate to blank page to fully initialize browser
    driver.get('about:blank')
    
    # Make sure browser is ready
    try:
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script('return document.readyState') == 'complete'
        )
        logger.debug("Browser fully initialized and ready")
    except Exception as e:
        logger.warning(f"Browser initialization warning: {e}")
        
    logger.debug("Initialized headless Chrome WebDriver with anti-bot evasion.")
    return driver

def retry_with_backoff(func):
    """Decorator to retry a function with exponential backoff on exceptions."""
    def wrapper(*args, **kwargs):
        delay = 1
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error on attempt {attempt} for {func.__name__}: {e}")
                if attempt == MAX_RETRIES:
                    logger.error(f"Max retries reached for {func.__name__}. Raising exception.")
                    raise
                else:
                    logger.info(f"Retrying {func.__name__} in {delay} seconds...")
                    time.sleep(delay)
                    delay *= RETRY_BACKOFF_FACTOR
    return wrapper

@retry_with_backoff
def get_total_cast_pages(driver):
    """Get total number of cast pages from the /casts index."""
    driver.get(CASTS_URL)
    logger.debug(f"Loaded casts index page: {CASTS_URL}")
    
    # Wait for page to load completely
    time.sleep(2)
    
    try:
        # Try multiple selectors for pagination
        selectors = [
            "ul.pagination li a",  # Original selector
            "div.pagination a",     # Alternative pagination format
            "a[href*='page=']",     # Links with page parameter
            "a.page-link"           # Bootstrap pagination links
        ]
        
        page_numbers = []
        for selector in selectors:
            pagination_elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if pagination_elements:
                logger.debug(f"Found pagination elements using selector: {selector}")
                
                # Extract page numbers from elements
                for elem in pagination_elements:
                    # Try to get number from text
                    text = elem.text.strip()
                    if text and text.isdigit():
                        page_numbers.append(int(text))
                        continue
                        
                    # Try to get number from href attribute
                    href = elem.get_attribute("href")
                    if href and "page=" in href:
                        try:
                            page_param = href.split("page=")[1].split("&")[0]
                            if page_param.isdigit():
                                page_numbers.append(int(page_param))
                        except (IndexError, ValueError):
                            pass
                
                if page_numbers:
                    break
        
        # If we found page numbers, use the maximum as total pages
        if page_numbers:
            total_pages = max(page_numbers)
        else:
            # Fallback: Check if there's a 'Next' or 'Last' button
            next_buttons = driver.find_elements(By.CSS_SELECTOR, "a[rel='next'], a:contains('Next'), a:contains('»')")
            if next_buttons:
                logger.debug("No page numbers found, but 'Next' button exists. Setting total_pages to 10.")
                total_pages = 10  # Reasonable default if we can't determine exact count
            else:
                logger.debug("No pagination found. Assuming single page.")
                total_pages = 1
        
        logger.debug(f"Detected total cast pages: {total_pages}")
        return total_pages
        
    except Exception as e:
        logger.error(f"Failed to detect total cast pages: {e}")
        # Dump HTML for debugging
        html = driver.page_source
        with open("debug_pagination.html", "w", encoding="utf-8") as f:
            f.write(html)
        logger.error("Dumped HTML for debugging")
        
        # Default to a reasonable number if we can't determine
        logger.info("Defaulting to 5 pages")
        return 5

@retry_with_backoff
def scrape_cast_links(driver, page_num):
    """Scrape all cast URLs on a given cast page number."""
    url = f"{CASTS_URL}?page={page_num}"
    driver.get(url)
    logger.debug(f"Loaded cast page: {url}")
    try:
        # Wait for page to load completely
        time.sleep(2)
        
        # Try multiple selectors to find cast links
        selectors = [
            "div.cast-list a",  # Original selector
            "a[href^='/casts/']",  # Links that start with /casts/
            "a[href*='/cast/']",   # Links that contain /cast/
            "div.grid a",          # Grid layout links
            "div.cast a",           # Cast div links
            "a"                     # All links (fallback)
        ]
        
        cast_links = []
        for selector in selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            links = [elem.get_attribute("href") for elem in elements if elem.get_attribute("href")]
            # Filter links to only include those that look like cast links
            cast_links = [link for link in links if "/casts/" in link]
            if cast_links:
                logger.debug(f"Found {len(cast_links)} cast links using selector: {selector}")
                break
        
        if not cast_links:
            # Dump HTML and screenshot for debugging
            html = driver.page_source
            with open("debug_cast_page.html", "w", encoding="utf-8") as f:
                f.write(html)
            driver.save_screenshot("debug_cast_page.png")
            logger.error(f"No cast links found on page {page_num}. Dumped HTML and screenshot.")
            raise ValueError(f"No cast links found on page {page_num}")
        
        logger.debug(f"Found {len(cast_links)} cast links on page {page_num}")
        return cast_links
    except Exception as e:
        logger.error(f"Failed to scrape cast links on page {page_num}: {e}")
        raise

def pick_random_cast(cast_links):
    """Pick a random cast URL from the list."""
    if not cast_links:
        raise ValueError("No cast links to pick from.")
    chosen = random.choice(cast_links)
    logger.debug(f"Randomly picked cast URL: {chosen}")
    return chosen

@retry_with_backoff
def get_trailer_pages(driver, cast_url):
    """Scrape all trailer links (URLs containing /video/) from a cast page."""
    driver.get(cast_url)
    logger.debug(f"Loaded cast page: {cast_url}")
    try:
        # Wait for page to load completely
        time.sleep(2)
        
        # Try multiple selectors to find trailer links
        selectors = [
            "a[href*='/video/']",     # Original selector - links containing /video/
            "a[href*='/videos/']",    # Alternative pattern
            "div.video-list a",       # Video list links
            "div.grid a",            # Grid layout links
            "a"                       # All links (fallback)
        ]
        
        trailer_links = []
        for selector in selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            links = [elem.get_attribute("href") for elem in elements if elem.get_attribute("href")]
            # Filter links to only include those that look like video links
            video_links = [link for link in links if "/video/" in link or "/videos/" in link]
            if video_links:
                trailer_links = video_links
                logger.debug(f"Found {len(trailer_links)} trailer links using selector: {selector}")
                break
        
        if not trailer_links:
            # Dump HTML for debugging
            html = driver.page_source
            with open("debug_trailer_page.html", "w", encoding="utf-8") as f:
                f.write(html)
            logger.error(f"No trailer links found on cast page {cast_url}. Dumped HTML.")
            raise ValueError(f"No trailer links found on cast page {cast_url}")
        
        logger.debug(f"Found {len(trailer_links)} trailer links on cast page")
        return trailer_links
    except Exception as e:
        logger.error(f"Failed to scrape trailer links on cast page {cast_url}: {e}")
        raise

def sanitize_title(title, max_length=100, add_suffix=False):
    """Sanitize title for filesystem safety and optionally append a random suffix.
    
    Args:
        title: The original title to sanitize
        max_length: Maximum length of the resulting title (excluding suffix)
        add_suffix: Whether to add a random suffix for uniqueness
        
    Returns:
        A filesystem-safe title string
    """
    if not title:
        title = f"untitled_{int(time.time())}"
    
    # For titles that include a code (like 'ABC-123 Title'), we want to preserve the code portion
    # Extract potential code prefix (e.g., 'ABC-123 ' from 'ABC-123 Title')
    code_prefix = ''
    code_match = re.match(r'([A-Z]{2,5}-\d{3,5})\s+', title)
    if code_match:
        code_prefix = code_match.group(0)  # This includes the space after the code
        title_part = title[len(code_prefix):]  # The rest of the title after the code
    else:
        title_part = title
        
    # Replace unsafe characters with underscores in the title part only, preserving spaces and common punctuation
    sanitized_title = "".join(c if c.isalnum() or c in ' -_()[]' else '_' for c in title_part)
    
    # Replace multiple spaces or underscores with a single one
    sanitized_title = re.sub(r'[_\s]+', ' ', sanitized_title).strip()
    
    # Trim to max length (accounting for code prefix length)
    max_title_length = max_length - len(code_prefix)
    if max_title_length > 0:
        sanitized_title = sanitized_title[:max_title_length]
        
    # Combine code prefix with sanitized title
    final_title = code_prefix + sanitized_title
    
    # Add random suffix if requested
    if add_suffix:
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        final_title = f"{final_title}_{suffix}"
        
    logger.debug(f"Sanitized title: {final_title}")
    return final_title

def extract_video_code(title_or_url):
    """Extract video code (e.g., CAWD-136) from title or URL"""
    # Common JAV code patterns
    patterns = [
        r'([A-Z]{2,5})-?(\d{3,5})',  # Standard format like CAWD-136
        r'([A-Z]{2,5})(\d{3,5})',      # No hyphen format like CAWD136
        r'([A-Z]{2,5}) ?(\d{3,5})'     # Space instead of hyphen
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title_or_url, re.IGNORECASE)
        if match:
            prefix, number = match.groups()
            # Format consistently with hyphen
            return f"{prefix.upper()}-{number.zfill(3)}"
    
    # If no code found, extract from URL as last resort
    if '/' in title_or_url:
        filename = title_or_url.split('/')[-1]
        # Try to clean up filename
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', filename)
        if clean_name:
            return clean_name
    
    # If we really can't find anything, use timestamp
    return f"UNKNOWN-{int(time.time())}"

@retry_with_backoff
def parse_trailer(driver, trailer_url):
    """Parse trailer metadata from trailer page."""
    try:
        with wait_for_page_load(driver):
            driver.get(trailer_url)
        # Additional wait for dynamic content
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script('return document.readyState') == 'complete'
        )
        logger.debug(f"Loaded trailer page: {trailer_url}")
    except Exception as e:
        logger.warning(f"Page load wait failed, continuing anyway: {e}")
        # Fallback
        driver.get(trailer_url)
        time.sleep(2)
    
    try:
        # Initialize metadata dictionary
        metadata = {
            'url': trailer_url,
            'scraped_date': datetime.datetime.now().isoformat(),
            'title': '',
            'original_title': '',
            'thumbnail_url': '',
            'video_code': '',
            'description': '',
            'tags': [],
            'actress': '',
            'studio': '',
            'release_date': ''
        }
        
        # Method 1: Open Graph meta tags (most reliable)
        try:
            # Title
            og_title = driver.find_element(By.CSS_SELECTOR, "meta[property='og:title']").get_attribute("content")
            if og_title:
                metadata['title'] = og_title
                metadata['original_title'] = og_title
            
            # Thumbnail
            og_image = driver.find_element(By.CSS_SELECTOR, "meta[property='og:image']").get_attribute("content")
            if og_image:
                metadata['thumbnail_url'] = og_image
            
            # Description
            try:
                og_desc = driver.find_element(By.CSS_SELECTOR, "meta[property='og:description']").get_attribute("content")
                if og_desc:
                    metadata['description'] = og_desc
            except NoSuchElementException:
                pass
                
            logger.debug("Found metadata using Open Graph tags")
        except NoSuchElementException:
            logger.debug("Open Graph tags not found, trying alternative methods")
        
        # Method 2: Page title and structured data
        if not metadata['title']:
            try:
                page_title = driver.title
                if page_title and page_title != "":
                    metadata['title'] = page_title
                    metadata['original_title'] = page_title
            except Exception as e:
                logger.debug(f"Error getting page title: {e}")
        
        # Try to extract JSON-LD structured data
        try:
            json_ld_elements = driver.find_elements(By.CSS_SELECTOR, "script[type='application/ld+json']")
            for element in json_ld_elements:
                try:
                    json_content = element.get_attribute('textContent')
                    if json_content:
                        data = json.loads(json_content)
                        if isinstance(data, dict):
                            # Extract various fields if available
                            if 'name' in data and not metadata['title']:
                                metadata['title'] = data['name']
                            if 'image' in data and not metadata['thumbnail_url']:
                                if isinstance(data['image'], str):
                                    metadata['thumbnail_url'] = data['image']
                                elif isinstance(data['image'], dict) and 'url' in data['image']:
                                    metadata['thumbnail_url'] = data['image']['url']
                            if 'description' in data and not metadata['description']:
                                metadata['description'] = data['description']
                            if 'datePublished' in data:
                                metadata['release_date'] = data['datePublished']
                except Exception as json_err:
                    logger.debug(f"Error parsing JSON-LD: {json_err}")
        except Exception as e:
            logger.debug(f"Error finding structured data: {e}")
        
        # Try to find a prominent image if still missing
        if not metadata['thumbnail_url']:
            try:
                # Look for specific image patterns first
                image_selectors = [
                    "img[src*='thumb'], img.thumbnail, img.poster, img[src*='poster'], img[src*='cover']",
                    "img[alt*='cover'], img[alt*='poster'], img[alt*='thumbnail']",
                    "img[width>'200'][height>'200']",
                    "img" # Fallback to any image
                ]
                
                for selector in image_selectors:
                    images = driver.find_elements(By.CSS_SELECTOR, selector)
                    if images:
                        # Get the largest image based on width/height attributes if available
                        best_img = None
                        max_size = 0
                        
                        for img in images:
                            try:
                                width = img.get_attribute('width')
                                height = img.get_attribute('height')
                                if width and height:
                                    size = int(width) * int(height)
                                    if size > max_size:
                                        max_size = size
                                        best_img = img
                            except:
                                pass
                        
                        # If we couldn't determine size, just use the first one
                        image_url = (best_img or images[0]).get_attribute("src")
                        if image_url:
                            metadata['thumbnail_url'] = image_url
                            logger.debug(f"Found image using selector: {selector}")
                            break
            except Exception as e:
                logger.debug(f"Error finding images: {e}")
        
        # Extract any additional metadata from page content
        try:
            # Look for common tag patterns
            tag_elements = driver.find_elements(By.CSS_SELECTOR, ".tags a, .tag a, .categories a, .genre a, a[href*='tag'], a[href*='category'], a[href*='genre'], a[href*='genres']")
            if tag_elements:
                for tag_el in tag_elements:
                    tag_text = tag_el.text.strip()
                    if tag_text and tag_text not in metadata['tags']:
                        metadata['tags'].append(tag_text)
                        
            # If no tags found with the above method, try looking at the page text for genre-like terms
            if not metadata['tags']:
                # Extract the body text and look for common genre indicators
                body_text = driver.find_element(By.TAG_NAME, 'body').text
                potential_genres = re.findall(r'(Genre|Category|Tag|Tags|Genres|Categories)\s*:\s*([^\n]+)', body_text)
                for genre_match in potential_genres:
                    genre_list = genre_match[1].split(',')
                    for genre in genre_list:
                        cleaned_genre = genre.strip()
                        if cleaned_genre and cleaned_genre not in metadata['tags']:
                            metadata['tags'].append(cleaned_genre)
        except Exception as e:
            logger.debug(f"Error extracting tags: {e}")
            
        # Try to extract studio information
        try:
            # First try using common selectors
            studio_elements = driver.find_elements(By.CSS_SELECTOR, ".studio a, a[href*='studio'], .maker a, a[href*='maker'], .publisher a, a[href*='publisher'], .label a, a[href*='label']")
            if studio_elements and studio_elements[0].text.strip():
                metadata['studio'] = studio_elements[0].text.strip()
            else:
                # Try to find studio by looking for text patterns in the page
                body_text = driver.find_element(By.TAG_NAME, 'body').text
                studio_match = re.search(r'(Studio|Maker|Publisher|Label|Company)\s*:\s*([^\n]+)', body_text)
                if studio_match:
                    metadata['studio'] = studio_match.group(2).strip()
        except Exception as e:
            logger.debug(f"Error extracting studio: {e}")
            
        # Try to extract release date
        try:
            # Look for date elements
            date_elements = driver.find_elements(By.CSS_SELECTOR, ".date, .release-date, .released, time[datetime], [itemprop='datePublished']")
            if date_elements and date_elements[0].text.strip():
                metadata['release_date'] = date_elements[0].text.strip()
            else:
                # Try to find date by looking for text patterns in the page
                body_text = driver.find_element(By.TAG_NAME, 'body').text
                date_match = re.search(r'(Release Date|Released|Date|Published)\s*:\s*([^\n]+)', body_text)
                if date_match:
                    metadata['release_date'] = date_match.group(2).strip()
        except Exception as e:
            logger.debug(f"Error extracting release date: {e}")
        
        # If still no title, use URL as fallback
        if not metadata['title']:
            metadata['title'] = trailer_url.split('/')[-1]
            metadata['original_title'] = metadata['title']
            logger.debug("Using URL fragment as title fallback")
        
        # If still no image, use a placeholder
        if not metadata['thumbnail_url']:
            metadata['thumbnail_url'] = "https://via.placeholder.com/640x360.png?text=No+Thumbnail"
            logger.debug("Using placeholder image")
        
        # Extract video code from title or URL
        if not metadata['video_code']:
            metadata['video_code'] = extract_video_code(metadata['title'])
            if metadata['video_code'] == f"UNKNOWN-{int(time.time())}":
                # Try URL instead
                metadata['video_code'] = extract_video_code(trailer_url)
        
        # Try to extract actress information if not already set
        try:
            # Look for actress elements using various selectors
            actress_elements = driver.find_elements(By.CSS_SELECTOR, ".actress a, a[href*='actress'], a[href*='cast'], a[href*='casts'], a[href*='star'], a[href*='model'], a[href*='idol']")
            if actress_elements:
                actress_names = []
                for actress in actress_elements:
                    name = actress.text.strip()
                    if name and name not in actress_names:
                        actress_names.append(name)
                if actress_names:
                    metadata['actress'] = ', '.join(actress_names)
            
            # If no actress found with selectors, try looking at the page text
            if not metadata['actress']:
                body_text = driver.find_element(By.TAG_NAME, 'body').text
                actress_match = re.search(r'(Actress|Cast|Star|Model|Idol|Performer)\s*:\s*([^\n]+)', body_text)
                if actress_match:
                    metadata['actress'] = actress_match.group(2).strip()
                    
            # If we have an actress from the URL, use it as fallback
            if not metadata['actress'] and 'actress_from_url' in locals():
                metadata['actress'] = actress_from_url
        except Exception as e:
            logger.debug(f"Error extracting actress: {e}")
        
        # Just return the original title - we'll format it with the code in the main function
        logger.debug(f"Parsed trailer metadata: code={metadata['video_code']}, title={metadata['title']}")
        return metadata['title'], metadata['thumbnail_url'], metadata
        
    except Exception as e:
        logger.error(f"Failed to parse trailer metadata on {trailer_url}: {e}")
        # Dump HTML for debugging
        html = driver.page_source
        with open("debug_metadata_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        logger.error(f"Dumped HTML for debugging")
        raise

def download_thumbnail(url, filepath):
    """Download thumbnail image via requests streaming with content-type validation."""
    logger.debug(f"Downloading thumbnail from {url} to {filepath}")
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Make request with stream=True to avoid loading entire file into memory
        response = requests.get(url, stream=True, timeout=30, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        
        # Validate content type is an image
        content_type = response.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            # Try to guess from URL if header is missing or incorrect
            guessed_type = mimetypes.guess_type(url)[0]
            if not guessed_type or not guessed_type.startswith('image/'):
                logger.warning(f"Content-Type '{content_type}' is not an image. URL: {url}")
                # Continue anyway, but log the warning
        
        # Write file in chunks to avoid memory issues
        with open(filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        # Verify file size
        file_size = os.path.getsize(filepath)
        if file_size == 0:
            logger.error(f"Downloaded thumbnail has zero size: {filepath}")
            os.remove(filepath)  # Remove empty file
            return False
            
        logger.info(f"Thumbnail downloaded: {filepath} ({file_size} bytes)")
        return True
    except Exception as e:
        logger.error(f"Failed to download thumbnail {url}: {e}")
        # Clean up partial file if it exists
        if os.path.exists(filepath):
            os.remove(filepath)
        return False

def video_progress_hook(d):
    if d['status'] == 'downloading':
        logger.debug(f"Downloading video: {d['_percent_str']} at {d['_speed_str']} ETA {d['_eta_str']}")
    elif d['status'] == 'finished':
        logger.info(f"Finished downloading video: {d['filename']}")

@retry_with_backoff
def extract_video_source(driver, page_url):
    """Extract the actual video source URL from the trailer page."""
    logger.debug(f"Extracting video source from {page_url}")
    
    # Parse the video code from URL for direct m3u8 construction attempt later
    video_code = None
    try:
        # Example: https://javtrailers.com/video/h_113kpp00078 -> h_113kpp00078
        video_code = page_url.split('/')[-1]
        logger.debug(f"Extracted video code from URL: {video_code}")
    except Exception as e:
        logger.debug(f"Failed to extract video code from URL: {e}")
    
    # Navigate to the page if not already there
    current_url = driver.current_url
    if current_url != page_url:
        try:
            with wait_for_page_load(driver):
                driver.get(page_url)
            # Additional wait for dynamic content to load
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
        except Exception as e:
            logger.warning(f"Page load wait failed, continuing anyway: {e}")
            # Fallback if wait_for_page_load fails
            driver.get(page_url)
            time.sleep(2)  # Fallback wait
    
    # Try multiple methods to find video source
    video_url = None
    active_frames = []  # Keep track of frames we enter
    
    # Method 1: Look for video tags
    try:
        video_elements = WebDriverWait(driver, 5).until(
            EC.presence_of_all_elements_located((By.TAG_NAME, "video"))
        )
        for video in video_elements:
            try:
                src = video.get_attribute("src")
                if src and (src.endswith(".mp4") or "/video/" in src or ".m3u8" in src):
                    video_url = src
                    logger.debug(f"Found video source in video tag: {video_url}")
                    break
            except (StaleElementReferenceException, WebDriverException):
                continue  # Element might have become stale, skip it
    except (TimeoutException, WebDriverException) as e:
        logger.debug(f"No video tags found: {e}")
    
    # Method 2: Look for source tags inside video elements
    if not video_url:
        try:
            source_elements = driver.find_elements(By.CSS_SELECTOR, "video source")
            for source in source_elements:
                try:
                    src = source.get_attribute("src")
                    if src and (src.endswith(".mp4") or "/video/" in src or ".m3u8" in src):
                        video_url = src
                        logger.debug(f"Found video source in source tag: {video_url}")
                        break
                except (StaleElementReferenceException, WebDriverException):
                    continue  # Element might have become stale, skip it
        except Exception as e:
            logger.debug(f"Error finding source tag: {e}")
    
    # Method 3: Execute JavaScript to find video sources
    if not video_url:
        try:
            # Extended script to find both direct sources and streaming URLs
            js_script = """
            var sources = [];
            
            // Find video elements and their sources
            var videos = document.getElementsByTagName('video');
            for (var i = 0; i < videos.length; i++) {
                // Direct src attribute
                if (videos[i].src) sources.push(videos[i].src);
                
                // Current source via currentSrc property (more reliable for active videos)
                if (videos[i].currentSrc) sources.push(videos[i].currentSrc);
            }
            
            // Find source elements
            var sourceTags = document.getElementsByTagName('source');
            for (var i = 0; i < sourceTags.length; i++) {
                if (sourceTags[i].src) sources.push(sourceTags[i].src);
            }
            
            // Look for HLS/DASH sources in media elements
            try {
                var mediaElements = document.querySelectorAll('[data-hls-url], [data-dash-url], [data-src]');
                for (var i = 0; i < mediaElements.length; i++) {
                    var el = mediaElements[i];
                    if (el.dataset.hlsUrl) sources.push(el.dataset.hlsUrl);
                    if (el.dataset.dashUrl) sources.push(el.dataset.dashUrl);
                    if (el.dataset.src) sources.push(el.dataset.src);
                }
            } catch(e) {}
            
            // Look for sources in common player setups
            
            // JW Player
            if (window.jwplayer) {
                try {
                    var players = jwplayer();
                    if (players.getPlaylist && players.getPlaylist()[0]) {
                        sources.push(players.getPlaylist()[0].file);
                    }
                } catch(e) {}
            }
            
            // VideoJS
            if (window.videojs) {
                try {
                    var vjsPlayers = document.querySelectorAll('.video-js');
                    for (var i = 0; i < vjsPlayers.length; i++) {
                        var player = videojs.getPlayer(vjsPlayers[i]);
                        if (player && player.src()) {
                            sources.push(player.src());
                        }
                    }
                } catch(e) {}
            }
            
            // HTML5 video
            var videoElements = document.querySelectorAll('video');
            for (var i = 0; i < videoElements.length; i++) {
                if (videoElements[i].querySelector('source')) {
                    var videoSources = videoElements[i].querySelectorAll('source');
                    for (var j = 0; j < videoSources.length; j++) {
                        if (videoSources[j].src) {
                            sources.push(videoSources[j].src);
                        }
                    }
                }
            }
            
            // Return all found sources
            return sources;
            """
            sources = driver.execute_script(js_script)
            if sources:
                # First, filter out any image files that might have been misidentified as videos
                filtered_sources = [src for src in sources if src and not (
                    src.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')))]
                
                if not filtered_sources:
                    logger.debug("No valid video sources found after filtering out images")
                    return None
                    
                # Check for streaming URLs first (m3u8, mpd)
                streaming_sources = [src for src in filtered_sources if src and (".m3u8" in src or ".mpd" in src)]
                if streaming_sources:
                    video_url = streaming_sources[0]  # Prefer streaming sources
                    logger.debug(f"Found streaming source via JavaScript: {video_url}")
                else:
                    # Then check for direct MP4 URLs
                    mp4_sources = [src for src in filtered_sources if src and (
                        src.lower().endswith(".mp4") or "/video/" in src or 
                        "video" in src.lower() or "player" in src.lower())]
                    
                    if mp4_sources:
                        video_url = mp4_sources[0]
                        logger.debug(f"Found MP4 source via JavaScript: {video_url}")
        except Exception as e:
            logger.debug(f"Error executing JavaScript to find sources: {e}")
    
    # Method 4: Look for iframe sources that might contain videos
    if not video_url:
        try:
            iframe_elements = driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframe_elements:
                try:
                    iframe_src = iframe.get_attribute("src")
                    if iframe_src and ("player" in iframe_src or "embed" in iframe_src or "video" in iframe_src):
                        logger.debug(f"Found potential video iframe: {iframe_src}")
                        
                        # Remember current context to safely return later
                        active_frames.append("default")
                        
                        # Switch to iframe and look for video sources
                        driver.switch_to.frame(iframe)
                        
                        # Try to find videos in the iframe
                        try:
                            # Wait for iframe content to load
                            WebDriverWait(driver, 5).until(
                                lambda d: d.execute_script('return document.readyState') == 'complete'
                            )
                            
                            # Check for video elements
                            inner_videos = driver.find_elements(By.TAG_NAME, "video")
                            for video in inner_videos:
                                try:
                                    src = video.get_attribute("src")
                                    if src and (src.endswith(".mp4") or "/video/" in src or ".m3u8" in src):
                                        video_url = src
                                        logger.debug(f"Found video source in iframe: {video_url}")
                                        break
                                except (StaleElementReferenceException, WebDriverException):
                                    continue
                                    
                            # If still no URL, try JavaScript extraction in the iframe
                            if not video_url:
                                iframe_sources = driver.execute_script(js_script)
                                if iframe_sources:
                                    for src in iframe_sources:
                                        if src and (src.endswith(".mp4") or ".m3u8" in src or ".mpd" in src):
                                            video_url = src
                                            logger.debug(f"Found video source in iframe via JavaScript: {video_url}")
                                            break
                        except Exception as iframe_error:
                            logger.debug(f"Error analyzing iframe content: {iframe_error}")
                        
                        # Switch back to main content
                        driver.switch_to.default_content()
                        active_frames.pop()  # Remove the frame from our tracking
                        
                        if video_url:
                            break
                except Exception as iframe_err:
                    logger.debug(f"Error processing iframe: {iframe_err}")
                    # Make sure we're back to the main content if there was an error
                    if active_frames:
                        driver.switch_to.default_content()
                        active_frames = []  # Reset frame tracking
        except Exception as e:
            logger.debug(f"Error checking iframes: {e}")
            # Make sure we're back in the main content
            if active_frames:
                try:
                    driver.switch_to.default_content()
                    active_frames = []  # Reset frame tracking
                except:
                    pass
    
    # Direct extraction of m3u8 URLs from HTML content as a last resort
    if not video_url and video_code:
        try:
            # Get the HTML source
            html = driver.page_source
            
            # First attempt: Search for playlist.m3u8 patterns
            m3u8_patterns = [
                f'https://media.javtrailers.com/hlsvideo/freepv/.+?/{video_code}/playlist.m3u8',
                f'https://cc3001.dmm.co.jp/hlsvideo/freepv/.+?/{video_code}/playlist.m3u8',
                f'\"(https://[^\"]+?/hlsvideo/freepv/[^\"]+?/{video_code}/playlist.m3u8)\"',
                f'(https://[^\"]+?/hlsvideo/freepv/[^\"]+?/{video_code}/playlist.m3u8)',
                r'(https://[^\"]+?/hlsvideo/freepv/[^\"]+?/playlist.m3u8)',
                r'\"(https://[^\"]+?\.m3u8)\"',
                r'(https://[^\"]+?\.m3u8)',
            ]
            
            for pattern in m3u8_patterns:
                matches = re.findall(pattern, html)
                if matches:
                    for match in matches:
                        # Check if the match is a tuple (from capturing groups)
                        if isinstance(match, tuple):
                            match = match[0]  # Get the first capturing group
                            
                        # Clean up any JSON escaping
                        clean_url = match.replace('\\/', '/').replace('\\/','/')
                        
                        if 'm3u8' in clean_url.lower():
                            logger.debug(f"Found m3u8 URL using regex pattern: {clean_url}")
                            video_url = clean_url
                            break
                if video_url:
                    break
                    
            # If still no URL, try to construct one based on common patterns
            if not video_url:
                # Try to construct common URL patterns
                possible_urls = [
                    f"https://media.javtrailers.com/hlsvideo/freepv/{video_code[0]}/{video_code[:3]}/{video_code}/playlist.m3u8",
                    f"https://media.javtrailers.com/litevideo/freepv/{video_code[0]}/{video_code[:3]}/{video_code}/{video_code}_dmb_w.mp4"
                ]
                
                for url in possible_urls:
                    try:
                        # Try to verify if the URL exists without downloading the full content
                        response = requests.head(url, timeout=5, headers={"User-Agent": USER_AGENT})
                        if response.status_code == 200:
                            logger.debug(f"Successfully verified constructed URL: {url}")
                            video_url = url
                            break
                    except Exception as e:
                        logger.debug(f"Failed to verify URL {url}: {e}")
        except Exception as e:
            logger.error(f"Error during direct m3u8 extraction: {e}")
            
    # If we still don't have a video URL, dump the page for debugging
    if not video_url:
        html = driver.page_source
        with open("debug_video_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        logger.error(f"Failed to extract video source from {page_url}. Dumped HTML for debugging.")
        raise ValueError(f"Could not find video source on {page_url}")
    
    # Make sure URL is absolute
    if not video_url.startswith("http"):
        video_url = urljoin(page_url, video_url)
    
    logger.debug(f"Extracted video source URL: {video_url}")
    return video_url

@retry_with_backoff
def download_video_ffmpeg(url, output_path):
    """Download video using ffmpeg."""
    logger.debug(f"Attempting to download video with ffmpeg: {url} -> {output_path}")
    
    # Check if the URL is a streaming URL (HLS/DASH)
    is_streaming = False
    is_hls = False
    
    if url.endswith('.m3u8') or 'm3u8' in url:
        is_streaming = True
        is_hls = True
        logger.debug(f"Detected HLS stream: {url}")
    elif url.endswith('.mpd') or 'mpd' in url:
        is_streaming = True
        logger.debug(f"Detected DASH stream: {url}")
    
    try:
        # Build ffmpeg command
        cmd = ['ffmpeg', '-y']  # Overwrite output files without asking
        
        # Determine if this is an HLS/streaming URL
        is_streaming = False
        is_hls = False
        if url.endswith('.m3u8') or '.m3u8?' in url:
            is_streaming = True
            is_hls = True
        elif url.endswith('.mpd') or '.mpd?' in url:
            is_streaming = True
        
        # Construct ffmpeg command
        cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'info']
        
        # Add user agent
        cmd.extend(['-user_agent', USER_AGENT])
        
        # For HLS/streaming specific options
        if is_streaming:
            if is_hls:
                cmd.extend([
                    '-protocol_whitelist', 'file,http,https,tcp,tls,crypto,data',
                    '-allowed_extensions', 'ALL'
                ])
            
            # Add additional options to help with streaming
            cmd.extend([
                '-reconnect', '1',
                '-reconnect_streamed', '1',
                '-reconnect_delay_max', '10'
            ])
        
        # Add input URL
        cmd.extend(['-i', url])
        
        # Use copy codec to avoid encoder issues
        cmd.extend(['-c', 'copy'])
        
        # Add output file
        cmd.append(output_path)
        
        # Run ffmpeg command
        logger.debug(f"Running ffmpeg command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Check if file was created and has size > 0
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.debug(f"FFmpeg download succeeded: {output_path}")
            return True
        
        # If we got here, the download failed
        logger.error(f"FFmpeg error: {result.stderr}")
        logger.info("Streaming download failed, retrying with different options")
        raise Exception("Streaming download failed, will retry with different options")
        
    except Exception as e:
        logger.error(f"Error in download_video_ffmpeg: {str(e)}")
        # Clean up partial file if it exists
        if os.path.exists(output_path):
            os.remove(output_path)
        return False

def is_valid_video_url(url):
    """Check if a URL is likely a valid video URL and not an image or other non-video file."""
    if not url:
        return False
        
    # Check for common image extensions which should be rejected
    image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.svg')
    if url.lower().endswith(image_extensions):
        logger.warning(f"Detected image URL instead of video: {url}")
        return False
        
    # Check for common video extensions and patterns which should be accepted
    video_extensions = ('.mp4', '.webm', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.m3u8', '.mpd', '.ts')
    video_patterns = ('/video/', '/videos/', '/player/', '/embed/', '/stream/', '/watch/', 'movie', 'trailer')
    
    # Check extensions
    if url.lower().endswith(video_extensions):
        return True
        
    # Check patterns in URL
    for pattern in video_patterns:
        if pattern in url.lower():
            return True
            
    # Check content type using HEAD request (without downloading the full file)
    try:
        response = requests.head(url, timeout=10, headers={"User-Agent": USER_AGENT})
        content_type = response.headers.get('Content-Type', '').lower()
        
        # Valid video content types
        if 'video/' in content_type or 'application/octet-stream' in content_type:
            return True
            
        # Explicitly reject image types
        if 'image/' in content_type:
            logger.warning(f"Content-Type confirms this is an image, not video: {content_type}")
            return False
            
    except Exception as e:
        logger.debug(f"Error checking content-type of URL: {e}")
        # Continue with pattern matching if HEAD request fails
        
    # If we couldn't definitively determine, log a warning and return true to let ffmpeg try
    logger.warning(f"Could not definitively determine if URL is a video: {url}")
    return False  # Be conservative - if we're not sure it's a video, don't try

def download_javtrailers_direct(video_code, filepath):
    """Special direct download method specifically for javtrailers.com"""
    logger.debug(f"Attempting specialized direct download for video code: {video_code}")
    
    # Create parent directory if it doesn't exist
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    # Remove any trailing 'r' which seems to be added to some IDs
    if video_code.endswith('r'):
        video_code = video_code[:-1]
    
    # Clean up the video code - removing any potential file extension
    video_code = video_code.split('.')[0].strip()
    
    logger.debug(f"Cleaned video code: {video_code}")
    
    # Try a direct approach - extract the DVD ID pattern
    # For codes like 41hrdv00531, extract hrdv and 531
    dvd_code = None
    num_code = None
    
    # Try to match patterns like: 41hrdv00531
    match1 = re.search(r'(\d+)?([a-zA-Z_]+)(\d+)', video_code)
    if match1:
        groups = match1.groups()
        if len(groups) >= 3:
            prefix = groups[0] or ''
            dvd_code = groups[1]
            num_code = groups[2]
            logger.debug(f"Extracted DVD code: {dvd_code}, Number: {num_code}")
    
    # URLs for DMM videos specifically
    dmm_urls = []
    
    # If we found a DVD code and number, try specific DMM URL patterns
    if dvd_code and num_code:
        # Build different URL variations
        # Format: https://cc3001.dmm.co.jp/litevideo/freepv/4/41h/41hrdv00531/41hrdv00531_dmb_w.mp4
        # or: https://media.javtrailers.com/litevideo/freepv/4/41h/41hrdv00531/41hrdv00531_dmb_w.mp4
        
        # Make the DVD code lowercase for URL
        dvd_code_lower = dvd_code.lower()
        
        # Different first letter formats
        first_letters = []
        if video_code[0].isdigit():
            first_letters.append(video_code[0])
        else:
            first_letters.append(video_code[0].lower())
        
        # Different second directory formats
        second_dirs = []
        if len(video_code) >= 3:
            second_dirs.append(video_code[:3].lower())
        if prefix:
            second_dirs.append(f"{prefix}{dvd_code_lower[:2]}")
        
        # Ensure we have something for second_dirs
        if not second_dirs:
            second_dirs.append(dvd_code_lower[:3])
        
        # Try variations of the full DVD ID
        full_ids = [video_code.lower()]
        
        # Try different domain and path combinations
        domains = [
            "https://cc3001.dmm.co.jp",
            "https://media.javtrailers.com"
        ]
        
        for domain in domains:
            for first_letter in first_letters:
                for second_dir in second_dirs:
                    for full_id in full_ids:
                        # MP4 direct URL format
                        dmm_urls.append(f"{domain}/litevideo/freepv/{first_letter}/{second_dir}/{full_id}/{full_id}_dmb_w.mp4")
                        
                        # HLS stream format
                        dmm_urls.append(f"{domain}/hlsvideo/freepv/{first_letter}/{second_dir}/{full_id}/playlist.m3u8")
    
    # Try common URL patterns for all javtrailers videos
    common_patterns = []
    first_char = video_code[0].lower()
    
    # Generate multiple possible path formats
    if len(video_code) >= 3:
        # Format for videos like h_113kpp00078
        if '_' in video_code:
            parts = video_code.split('_')
            prefix = parts[0]
            if len(parts) > 1 and len(parts[1]) >= 3:
                subprefix = f"{prefix}_{parts[1][:1]}"
                common_patterns.append(f"https://media.javtrailers.com/litevideo/freepv/{first_char}/{subprefix}/{video_code}/{video_code}_dmb_w.mp4")
                common_patterns.append(f"https://media.javtrailers.com/hlsvideo/freepv/{first_char}/{subprefix}/{video_code}/playlist.m3u8")
                common_patterns.append(f"https://cc3001.dmm.co.jp/litevideo/freepv/{first_char}/{subprefix}/{video_code}/{video_code}_dmb_w.mp4")
                common_patterns.append(f"https://cc3001.dmm.co.jp/hlsvideo/freepv/{first_char}/{subprefix}/{video_code}/playlist.m3u8")
        
        # Format for videos with alphanumeric codes
        subdir = video_code[:3].lower()
        common_patterns.append(f"https://media.javtrailers.com/litevideo/freepv/{first_char}/{subdir}/{video_code}/{video_code}_dmb_w.mp4")
        common_patterns.append(f"https://media.javtrailers.com/hlsvideo/freepv/{first_char}/{subdir}/{video_code}/playlist.m3u8")
        common_patterns.append(f"https://cc3001.dmm.co.jp/litevideo/freepv/{first_char}/{subdir}/{video_code}/{video_code}_dmb_w.mp4")
        common_patterns.append(f"https://cc3001.dmm.co.jp/hlsvideo/freepv/{first_char}/{subdir}/{video_code}/playlist.m3u8")
    
    # Combine all potential URLs
    all_urls = dmm_urls + common_patterns
    
    # Log the URLs we're trying
    logger.debug(f"Trying {len(all_urls)} potential URLs for video: {video_code}")
    
    # Try to download using each potential URL
    for url in all_urls:
        try:
            # First verify the URL exists
            logger.debug(f"Checking URL: {url}")
            response = requests.head(url, timeout=10, headers={"User-Agent": USER_AGENT})
            
            if response.status_code == 200:
                logger.info(f"Found working direct URL: {url}")
                
                # Try to download using ffmpeg
                if download_video_ffmpeg(url, filepath):
                    logger.info(f"Successfully downloaded video for {video_code} to {filepath}")
                    return True
                else:
                    logger.warning(f"FFMPEG download failed for URL: {url}")
        except Exception as e:
            logger.debug(f"Error checking URL {url}: {e}")
    
    # Last resort - try scraping the actual page
    try:
        page_url = f"https://javtrailers.com/video/{video_code}"
        response = requests.get(page_url, headers={"User-Agent": USER_AGENT})
        if response.status_code == 200:
            html_content = response.text
            
            # Look for m3u8 URLs in the HTML content
            m3u8_urls = re.findall(r'"(https://[^"]+\.m3u8)"', html_content)
            mp4_urls = re.findall(r'"(https://[^"]+\.mp4)"', html_content)
            
            # Try each URL found
            for url in m3u8_urls + mp4_urls:
                try:
                    if download_video_ffmpeg(url, filepath):
                        return True
                except Exception as e:
                    logger.debug(f"Error with scraped URL {url}: {e}")
    except Exception as e:
        logger.debug(f"Error scraping page: {e}")
    
    logger.error(f"All direct download attempts failed for video code: {video_code}")
    return False

def download_video(driver, url, filepath):
    """Download video using direct ffmpeg or fallback to yt-dlp with ffmpeg."""
    logger.debug(f"Starting video download process for {url}")

    # First try specialized direct download if this is javtrailers.com
    if 'javtrailers.com' in url:
        video_code = url.split('/')[-1]  # Extract code from URL
        if video_code:
            # Try specialized direct download first
            if download_javtrailers_direct(video_code, filepath):
                logger.info(f"Successfully downloaded full trailer using specialized direct method")
                return True
            
            # If direct download failed, try browser extraction method
            video_urls = extract_video_from_browser(driver, url)
            if video_urls:
                logger.info(f"Found {len(video_urls)} video URLs through browser extraction")
                for video_url in video_urls:
                    logger.info(f"Attempting to download from browser-extracted URL: {video_url}")
                    if download_video_ffmpeg(video_url, filepath):
                        logger.info(f"Successfully downloaded video using browser-extracted URL")
                        return True

    # Continue with normal extraction if direct methods failed
    try:
        video_url = extract_video_source(driver, url)
        
        # Validate the video URL before attempting to download
        if video_url and is_valid_video_url(video_url):
            logger.debug(f"Found valid video URL: {video_url}")
            # Create parent directory if it doesn't exist
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            # Try direct download with ffmpeg first
            if download_video_ffmpeg(video_url, filepath):
                logger.info(f"Successfully downloaded full trailer using direct ffmpeg method")
                return True
            logger.warning("Direct ffmpeg download failed, trying yt-dlp as fallback")
        else:
            if video_url:
                logger.warning(f"Found URL but it doesn't appear to be a valid video: {video_url}")
            else:
                logger.warning("No video URL could be extracted")
    except Exception as e:
        logger.warning(f"Failed to extract direct video URL: {e}")
        logger.info("Will try yt-dlp instead")
    
    # Try to download with yt-dlp as a fallback
    try:
        if download_with_ytdlp(url, filepath):
            logger.info(f"Successfully downloaded video using yt-dlp")
            return True
    except NameError as e:
        # If the function isn't defined yet, call our function directly
        try:
            # Configure YoutubeDL options
            ydl_opts = {
                'format': 'bestvideo+bestaudio/best/mp4',  # Prefer best quality
                'outtmpl': filepath,  # Output filename template
                'retries': 5,  # Number of retries
                'fragment_retries': 15,  # Number of retries for fragments
                'progress_hooks': [lambda d: logger.debug(f"yt-dlp progress: {d.get('status', 'unknown')}")],
                'quiet': False,
                'verbose': True,
                'no_warnings': False,
                'ignoreerrors': False,
                'noplaylist': True,  # Only download the video, not the playlist
                'merge_output_format': 'mp4',  # Always output as MP4
                'hls_prefer_native': False,  # Use FFmpeg for HLS
                'hls_use_mpegts': True,  # Use .ts container for HLS downloads
                'external_downloader': 'ffmpeg',  # Use ffmpeg as external downloader
                'ratelimit': 0,  # No rate limit
                'socket_timeout': 60,  # Socket timeout
                'extractor_retries': 5,  # Extractor retries
                'external_downloader_args': {
                    'ffmpeg': [
                        '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
                        '-user_agent', USER_AGENT,
                        '-analyzeduration', '20000000',  # Increase analysis time for streams
                        '-probesize', '50000000'  # Increase probing size for streams
                    ]
                },
                'http_headers': {
                    'User-Agent': USER_AGENT,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Sec-Fetch-Mode': 'navigate',
                    'Referer': url
                }
            }
            
            # Try to download with yt-dlp
            logger.info(f"Attempting to download with yt-dlp: {url}")
            
            # Create parent directory if it doesn't exist
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
            # Check if file was created and has size > 0
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                logger.info(f"Successfully downloaded video using yt-dlp to {filepath}")
                return True
            else:
                logger.warning(f"yt-dlp didn't produce output file at {filepath}")
                return False
        except Exception as e2:
            logger.error(f"Error downloading with direct yt-dlp: {e2}")
            return False
    except Exception as e:
        logger.error(f"Error downloading with yt-dlp: {e}")
        
    logger.error(f"All download methods failed for {url}")
    return False

def extract_video_from_browser(driver, url):
    """Extract video URL by monitoring network requests when playing the video."""
    logger.info(f"Attempting to extract video URL from browser for {url}")
    
    video_urls = []
    
    try:
        # First navigate to the video page if not already there
        current_url = driver.current_url
        if current_url != url:
            logger.debug(f"Navigating to video page: {url}")
            with wait_for_page_load(driver):
                driver.get(url)
            # Additional wait for dynamic content
            WebDriverWait(driver, 20).until(  # Increased timeout from 10 to 20 seconds
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            time.sleep(3)  # Increased from 2 to 3 seconds for more JS execution time
        
        # Extract video code for direct URL construction
        video_code = extract_video_code(url)
        if video_code:
            # Try to construct potential m3u8 URLs based on known patterns
            potential_m3u8_urls = [
                f"https://cc3001.dmm.co.jp/hlsvideo/freepv/{video_code[0]}/{video_code[:3]}/{video_code}/playlist.m3u8",
                f"https://media.javtrailers.com/hlsvideo/freepv/{video_code[0]}/{video_code[:3]}/{video_code}/playlist.m3u8",
                f"https://cc3001.dmm.co.jp/hlsvideo/freepv/{video_code[0]}/{video_code[:3]}/{video_code}/full_quality.m3u8",
                f"https://media.javtrailers.com/hlsvideo/freepv/{video_code[0]}/{video_code[:3]}/{video_code}/full_quality.m3u8",
            ]
            video_urls.extend(potential_m3u8_urls)
            logger.debug(f"Added {len(potential_m3u8_urls)} potential m3u8 URLs based on video code")
        
        # Method 1: Execute JavaScript to find all video sources
        try:
            logger.debug("Extracting video sources using JavaScript")
            video_sources = driver.execute_script("""
                const videoSources = [];
                // Get sources from video elements
                const videoElements = document.querySelectorAll('video');
                for (const video of videoElements) {
                    if (video.src) videoSources.push(video.src);
                    const sources = video.querySelectorAll('source');
                    for (const source of sources) {
                        if (source.src) videoSources.push(source.src);
                    }
                }
                
                // Look for .m3u8 or .mp4 URLs in the page source
                const pageSource = document.documentElement.outerHTML;
                const m3u8Matches = pageSource.match(/https?:[^"']+\.m3u8[^"']*/g);
                const mp4Matches = pageSource.match(/https?:[^"']+\.mp4[^"']*/g);
                
                if (m3u8Matches) videoSources.push(...m3u8Matches);
                if (mp4Matches) videoSources.push(...mp4Matches);
                
                // Advanced: Check iframes for video sources
                const iframes = document.querySelectorAll('iframe');
                for (const iframe of iframes) {
                    try {
                        if (iframe.contentDocument) {
                            const iframeVideos = iframe.contentDocument.querySelectorAll('video');
                            for (const video of iframeVideos) {
                                if (video.src) videoSources.push(video.src);
                                const sources = video.querySelectorAll('source');
                                for (const source of sources) {
                                    if (source.src) videoSources.push(source.src);
                                }
                            }
                        }
                    } catch(e) {
                        // Security error may occur due to same-origin policy
                        console.log('Could not access iframe content:', e);
                    }
                }
                
                return videoSources;
            """)
            
            if video_sources and isinstance(video_sources, list):
                for src in video_sources:
                    if src and is_valid_video_url(src):
                        video_urls.append(src)
                        logger.debug(f"Found JS video source: {src}")
        except Exception as e:
            logger.debug(f"Error executing JavaScript for sources: {e}")
        
        # Method 2: Try to click play button and check for sources again
        if not video_urls:
            try:
                logger.debug("Trying to click play button")
                # Find all potential play buttons
                play_selectors = [
                    ".play-button", ".vjs-big-play-button", ".jw-display-icon-container",
                    "[aria-label='Play']", ".ytp-large-play-button", ".plyr__control--overlaid",
                    ".video-js", "video", ".mejs-overlay-button"
                ]
                
                for selector in play_selectors:
                    try:
                        buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                        if buttons:
                            logger.debug(f"Found {len(buttons)} potential play elements with selector '{selector}'")
                            for button in buttons:
                                try:
                                    # Try to click the button using JavaScript (more reliable than Selenium click)
                                    driver.execute_script("arguments[0].click();", button)
                                    logger.debug(f"Clicked on {selector} element")
                                    time.sleep(3)  # Wait for video to start
                                    
                                    # Check for sources after clicking
                                    video_sources = driver.execute_script("""
                                        const videoSources = [];
                                        // Get sources from video elements
                                        const videoElements = document.querySelectorAll('video');
                                        for (const video of videoElements) {
                                            if (video.src) videoSources.push(video.src);
                                            const sources = video.querySelectorAll('source');
                                            for (const source of sources) {
                                                if (source.src) videoSources.push(source.src);
                                            }
                                        }
                                        
                                        // Look for .m3u8 or .mp4 URLs in the page source
                                        const pageSource = document.documentElement.outerHTML;
                                        const m3u8Matches = pageSource.match(/https?:[^"']+\\.m3u8[^"']*/g);
                                        const mp4Matches = pageSource.match(/https?:[^"']+\\.mp4[^"']*/g);
                                        
                                        if (m3u8Matches) videoSources.push(...m3u8Matches);
                                        if (mp4Matches) videoSources.push(...mp4Matches);
                                        
                                        return videoSources;
                                    """)
                                    
                                    if video_sources and isinstance(video_sources, list):
                                        for src in video_sources:
                                            if src and is_valid_video_url(src) and src not in video_urls:
                                                video_urls.append(src)
                                                logger.debug(f"Found video source after clicking: {src}")
                                    
                                    # If we found sources, break out of the loop
                                    if video_urls:
                                        break
                                except Exception as e:
                                    logger.debug(f"Error clicking button: {e}")
                            
                            # If we found sources, break out of the selector loop
                            if video_urls:
                                break
                    except Exception as e:
                        logger.debug(f"Error finding elements with selector '{selector}': {e}")
            except Exception as e:
                logger.debug(f"Error clicking play buttons: {e}")
        
        # Filter and prioritize video URLs
        if video_urls:
            # Remove blob: URLs as they can't be downloaded directly
            filtered_urls = [url for url in video_urls if not url.startswith('blob:')]
            
            # Prioritize m3u8 (streaming) URLs as they usually have better quality
            m3u8_urls = [url for url in filtered_urls if '.m3u8' in url]
            mp4_urls = [url for url in filtered_urls if '.mp4' in url]
            
            # Sort by priority: m3u8 first, then mp4
            priority_urls = m3u8_urls + mp4_urls
            
            if priority_urls:
                logger.info(f"Found {len(priority_urls)} video URLs through browser extraction")
                return priority_urls
            else:
                logger.warning("Found only blob: URLs which cannot be downloaded directly")
                return []
        
        logger.warning("No video URLs found in browser")
        return []
        
    except Exception as e:
        logger.error(f"Error extracting video URLs from browser: {e}")
        return []
    
    # Extract video code from URL for direct m3u8 construction
    video_code = None
    try:
        video_code = url.split('/')[-1]
    except:
        pass
        
    # Try to directly locate a video URL if we have a video code
    if video_code:
        try:
            # Try higher quality direct URLs first (prioritize HLS/m3u8 streams which often have better quality)
            possible_direct_urls = [
                # High quality HLS streams first
                f"https://cc3001.dmm.co.jp/hlsvideo/freepv/{video_code[0]}/{video_code[:3]}/{video_code}/playlist.m3u8",
                f"https://media.javtrailers.com/hlsvideo/freepv/{video_code[0]}/{video_code[:3]}/{video_code}/playlist.m3u8",
                
                # Try alternate HLS URL patterns with full quality indicators
                f"https://cc3001.dmm.co.jp/hlsvideo/freepv/{video_code[0]}/{video_code[:3]}/{video_code}/full_quality.m3u8",
                f"https://media.javtrailers.com/hlsvideo/freepv/{video_code[0]}/{video_code[:3]}/{video_code}/full_quality.m3u8",
                
                # Then try MP4 direct links (typically lower quality)
                f"https://cc3001.dmm.co.jp/litevideo/freepv/{video_code[0]}/{video_code[:3]}/{video_code}/{video_code}_dmb_w.mp4",
                f"https://media.javtrailers.com/litevideo/freepv/{video_code[0]}/{video_code[:3]}/{video_code}/{video_code}_dmb_w.mp4",
                
                # Try alternate high quality MP4 patterns
                f"https://cc3001.dmm.co.jp/litevideo/freepv/{video_code[0]}/{video_code[:3]}/{video_code}/{video_code}_hq.mp4",
                f"https://media.javtrailers.com/litevideo/freepv/{video_code[0]}/{video_code[:3]}/{video_code}/{video_code}_hq.mp4"
            ]
            
            for direct_url in possible_direct_urls:
                try:
                    logger.debug(f"Checking high quality URL: {direct_url}")
                    response = requests.head(direct_url, timeout=10, headers={"User-Agent": USER_AGENT})
                    if response.status_code == 200:
                        logger.info(f"Found direct high quality video URL: {direct_url}")
                        
                        # Try ffmpeg download with this direct URL
                        if download_video_ffmpeg(direct_url, filepath):
                            logger.info(f"Successfully downloaded full trailer using direct URL: {direct_url}")
                            return True
                except Exception as e:
                    logger.debug(f"Failed checking direct URL {direct_url}: {e}")
        except Exception as e:
            logger.debug(f"Error trying direct URLs in fallback: {e}")
    
    # Advanced fallback using yt-dlp with better options
    try:
        # Enhanced settings for better quality
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best/mp4',  # Prioritize highest quality formats
            'outtmpl': filepath,
            'retries': VIDEO_RETRY_COUNT + 2,  # Increase retry count
            'fragment_retries': 15,  # Add more retries for fragments (important for HLS)
            'progress_hooks': [video_progress_hook],
            'quiet': False,  # Set to False to see more debugging info
            'verbose': True,  # More verbose output to diagnose issues
            'no_warnings': False,
            'ignoreerrors': False,  # Don't ignore errors to see actual problems
            'noplaylist': True,
            'merge_output_format': 'mp4',
            'hls_prefer_native': False,  # Use ffmpeg for HLS
            'hls_use_mpegts': True,  # Use MPEG-TS format for HLS segments
            'external_downloader': 'ffmpeg',  # Use ffmpeg as external downloader
            'ratelimit': 0,  # No rate limit to get full quality
            'socket_timeout': 60,  # Increased timeout
            'extractor_retries': 5,  # More retries for extraction
            'external_downloader_args': {
                'ffmpeg': [
                    '-protocol_whitelist', 'file,http,https,tcp,tls,crypto', 
                    '-user_agent', USER_AGENT,
                    '-analyzeduration', '20000000',  # Increase analysis time for better detection
                    '-probesize', '50000000'  # Increase probe size for better stream detection
                ]
            },
            'http_headers': {
                'User-Agent': USER_AGENT,
                'Referer': url,  # Use the actual page as referer
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            },
        }
        
        # Try to extract video directly from the page
        try:
            with YoutubeDL(ydl_opts) as ydl:
                # Use yt-dlp's --dump-json to get video info without downloading
                info = ydl.extract_info(url, download=False)
                
                # If we got info but no download URL, try direct extraction from the returned info
                if info and 'url' in info:
                    direct_url = info['url']
                    logger.info(f"Using direct URL from yt-dlp info: {direct_url}")
                    if download_video_ffmpeg(direct_url, filepath):
                        return True
                    
                # If that failed, try normal download
                ydl.download([url])
        except Exception as first_error:
            logger.warning(f"First yt-dlp attempt failed: {first_error}")
            
            # Try a simpler approach as last resort
            simpler_opts = {
                'format': 'best',
                'outtmpl': filepath,
                'retries': VIDEO_RETRY_COUNT,
                'quiet': True,
                'noplaylist': True,
                'http_headers': {'User-Agent': USER_AGENT},
            }
            
            try:
                with YoutubeDL(simpler_opts) as ydl:
                    ydl.download([url])
            except Exception as e:
                logger.error(f"Second yt-dlp attempt also failed: {e}")
                return False
        
        # Check if file was successfully created
        if os.path.exists(filepath):
            file_size = os.path.getsize(filepath)
            if file_size > 0:
                file_size_mb = file_size / (1024 * 1024)
                logger.info(f"Successfully downloaded video with yt-dlp: {filepath} ({file_size_mb:.2f} MB)")
                return True
            else:
                logger.error(f"Video file exists but has zero size: {filepath}")
                os.remove(filepath)  # Remove empty file
            # Try more aggressive approaches if regular methods fail
        if not download_success:
            logger.info(f"Initial download methods failed, trying aggressive approaches for {url}")
            
            # Try more URL patterns based on the video code
            logger.info("Trying extended URL patterns from various sources")
            video_code = extract_video_code(url)
            if video_code:
                # Extended DMM patterns
                extended_patterns = []
                
                # Try with different prefixes and formats
                prefixes = ['https://cc3001.dmm.co.jp', 'https://cc3002.dmm.co.jp', 'https://media.javtrailers.com', 'https://stream.javtrailers.com']
                formats = ['litevideo/freepv', 'hlsvideo/freepv', 'sample/movie', 'trailer/movie']
                exts = ['.mp4', '/playlist.m3u8', '/master.m3u8', '/index.m3u8']
                
                # Try to normalize the code for URL construction
                normalized_code = video_code.replace('-', '').lower()
                if len(normalized_code) >= 1:
                    first_char = normalized_code[0]
                    
                    # Different pattern variations
                    if len(normalized_code) >= 3:
                        subdir = normalized_code[:3].lower()
                        for prefix in prefixes:
                            for fmt in formats:
                                for ext in exts:
                                    # Standard pattern
                                    extended_patterns.append(f"{prefix}/{fmt}/{first_char}/{subdir}/{normalized_code}/{normalized_code}_dmb_w{ext}")
                                    # Alternative pattern 
                                    extended_patterns.append(f"{prefix}/{fmt}/{first_char}/{subdir}/{normalized_code}/{ext}")
                
                # Try each URL pattern
                for pattern_url in extended_patterns:
                    try:
                        logger.debug(f"Trying extended pattern URL: {pattern_url}")
                        output_path = os.path.join(download_dir, f"{metadata['video_code']} {metadata['title']}.mp4")
                        metadata['video_path'] = output_path
                        
                        # Check if URL is accessible
                        try:
                            response = requests.head(pattern_url, timeout=5, headers={"User-Agent": USER_AGENT})
                            if response.status_code != 200:
                                continue  # Skip to next URL if not accessible
                        except Exception:
                            continue  # Skip if request fails
                        
                        if '.m3u8' in pattern_url.lower():
                            download_success = download_video_ffmpeg(pattern_url, output_path)
                        else:
                            download_success = download_video(pattern_url, output_path)
                            
                        if download_success:
                            logger.info(f"Successfully downloaded video using extended pattern: {pattern_url}")
                            break
                    except Exception as e:
                        logger.debug(f"Error with extended pattern URL {pattern_url}: {e}")
            
            # Finally, if all else fails, try yt-dlp with aggressive settings
            if not download_success:
                logger.info(f"Attempting to download with aggressive yt-dlp settings: {url}")
                try:
                    output_path = os.path.join(download_dir, f"{metadata['video_code']} {metadata['title']}.mp4")
                    metadata['video_path'] = output_path
                    download_success = download_with_ytdlp(url, output_path, aggressive=True)
                except Exception as e:
                    logger.error(f"Error downloading with aggressive yt-dlp: {e}")
    except Exception as e:
        logger.error(f"All download methods failed for {url}")
        logger.error(f"Failed to download video for {metadata['video_code']} {metadata['title']}: {e}")

    # Save metadata even if download failed
    metadata_path = os.path.join(download_dir, f"{metadata['video_code']} {metadata['title']}.json")
    metadata['download_date'] = datetime.datetime.now().isoformat()
    if download_success:
        metadata['download_success'] = True
        metadata['downloaded_date'] = datetime.datetime.now().isoformat()
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    logger.debug(f"Saved metadata to {metadata_path}")
    logger.info(f"Saved metadata to {metadata_path}")

    return download_success, metadata['video_path'] if download_success else None, metadata['thumbnail_path'] if 'thumbnail_path' in metadata else None

def ensure_directories(base_path, actress_name, video_code):
    """Ensure download directories exist with the requested structure.
    
    Structure:  downloads/[actress_name]/[video_code]/
    
    Returns:
        content_dir: Directory for both video and thumbnail
    """
    # Create base actress directory
    actress_dir = os.path.join(base_path, actress_name)
    if not os.path.exists(actress_dir):
        os.makedirs(actress_dir)
        logger.debug(f"Created actress directory: {actress_dir}")
    
    # Create video code subdirectory
    video_dir = os.path.join(actress_dir, video_code)
    if not os.path.exists(video_dir):
        os.makedirs(video_dir)
        logger.debug(f"Created video directory: {video_dir}")
    
    return video_dir

def get_actress_name(cast_url):
    """Extract full actress name from cast URL."""
    # Get the full name from the URL
    actress_slug = os.path.basename(cast_url)
    
    # Use the driver to get the actual name from the page if available
    try:
        # Try to extract the full proper name from the page title or content
        # For now, we'll convert the slug to a more readable format
        # Replace hyphens with spaces and capitalize words
        full_name = ' '.join(word.capitalize() for word in actress_slug.split('-'))
        logger.debug(f"Extracted full actress name: {full_name} from {actress_slug}")
        return full_name
    except Exception as e:
        logger.warning(f"Could not extract full name, using slug: {actress_slug}")
        return actress_slug

def main():
    driver = None
    try:
        driver = init_driver()
        total_pages = get_total_cast_pages(driver)
        random_page = random.randint(1, total_pages)
        logger.info(f"Randomly selected cast page: {random_page} of {total_pages}")

        cast_links = scrape_cast_links(driver, random_page)
        cast_url = pick_random_cast(cast_links)
        
        # Get actress name from cast URL
        actress_name = get_actress_name(cast_url)
        logger.info(f"Processing actress: {actress_name}")

        # Get trailer links
        trailer_links = get_trailer_pages(driver, cast_url)
        if not trailer_links:
            logger.error("No trailer links found, exiting.")
            return

        # Track statistics
        successful_downloads = 0
        failed_downloads = 0
        total_videos = len(trailer_links)
        
        logger.info(f"Found {total_videos} videos for actress {actress_name}")
        
        # Process each trailer
        for i, trailer_url in enumerate(trailer_links, 1):
            try:
                logger.info(f"Processing video {i} of {total_videos} for {actress_name}: {trailer_url}")
                
                # Get the metadata
                # Title might not be accurate on some sites, so we're going to get it from elsewhere if possible
                title, thumbnail_url, metadata = parse_trailer(driver, trailer_url)
                
                # Thumbnail URL extraction is essential for identifying the video
                if not thumbnail_url:
                    logger.warning(f"No thumbnail found for trailer {trailer_url}, skipping")
                    continue
                    
                # Get the video ID code from the metadata or extract it from the URL
                video_code = metadata.get('video_code', '')
                if not video_code or video_code.startswith('UNKNOWN'):
                    video_code = extract_video_code(trailer_url)
                
                # Skip if we couldn't identify the video
                if not video_code:
                    logger.warning(f"Could not extract video code for {trailer_url}, skipping")
                    continue
                    
                # Check if the description field contains a better title (often the case with javtrailers)
                # Many sites put the full descriptive title in the description field
                description = metadata.get('description', '')
                
                # Use the description as the title if it's more descriptive
                # We check if it contains the video code, is longer than the current title,
                # and doesn't contain the generic 'Jav streaming Online Japanese Adult Video' phrase
                if description and 'Jav streaming Online Japanese Adult Video' not in description:
                    if video_code in description or len(description) > len(title):
                        logger.info(f"Using description as title: {description}")
                        title = description
                        metadata['title'] = description
                        metadata['original_title'] = description
                        
                # If title still has the generic text, try to create a better title
                if 'Jav streaming Online Japanese Adult Video' in title:
                    if description and len(description) > 0:
                        # Use description even if it doesn't contain the code
                        logger.info(f"Using description as title (generic title detected): {description}")
                        title = description
                        metadata['title'] = description
                        metadata['original_title'] = description
                
                logger.debug(f"Parsed trailer metadata: code={video_code}, title={title}")
                
                # Get the original title from metadata
                original_title = metadata.get('original_title', '')
                if not original_title:
                    original_title = metadata['title']
                
                # Get actress name from metadata if available, otherwise use the one from URL
                directory_actress_name = metadata.get('actress', '').strip()
                if not directory_actress_name:
                    directory_actress_name = actress_name
                    
                # If the actress name is a list (comma separated), use the first one for the directory
                if ',' in directory_actress_name:
                    directory_actress_name = directory_actress_name.split(',')[0].strip()
                    
                # Make sure we have an actress name for the directory
                if not directory_actress_name:
                    directory_actress_name = 'unknown_actress'
                    
                # Create directory structure based on the requirements
                # downloads/[actress_name]/[video_code]/
                content_dir = ensure_directories(DOWNLOAD_DIR, directory_actress_name, video_code)
                
                # Format filename as '{code} {title}' as shown on javtrailers site
                # Check if the title already contains the video code to avoid duplication
                # Make this check case-insensitive and handle various formats
                
                # Normalize the video code for comparison (remove any trailing r, etc.)
                normalized_code = video_code.split('.')[0].strip().upper()
                
                # Also normalize the code by removing leading zeros in the numeric part
                # This helps with formats like HRD-00038 vs HRD-38
                code_parts = re.match(r'([A-Z]+)[-\s]*(\d+)', normalized_code)
                if code_parts:
                    prefix = code_parts.group(1)
                    number = code_parts.group(2).lstrip('0')  # Remove leading zeros
                    canonical_code = f"{prefix}-{number}"
                else:
                    canonical_code = normalized_code
                
                logger.debug(f"Normalized code for comparison: {normalized_code} -> {canonical_code}")
                
                # Check if the title already contains the code in various formats
                title_has_code = False
                
                # Get the normalized version of the title for comparison
                title_upper = original_title.upper()
                
                # Check for exact code match at start (e.g., 'HRD-38 TITLE')
                if title_upper.startswith(normalized_code) or title_upper.startswith(canonical_code):
                    title_has_code = True
                # Check for code with different zero padding (e.g., 'HRD-00038 TITLE')
                elif re.search(f'^{re.escape(prefix)}-?0*{number}\\s', title_upper):
                    title_has_code = True
                # Check for code without hyphen (e.g., 'HRD38 TITLE')
                elif re.search(f'^{re.escape(prefix)}0*{number}\\s', title_upper):
                    title_has_code = True
                
                if title_has_code:
                    formatted_filename = original_title
                    logger.debug(f"Title already contains code {normalized_code}, using original title")
                else:
                    formatted_filename = f"{video_code} {original_title}"
                    logger.debug(f"Adding code {video_code} to title")
                
                logger.info(f"Using filename format: '{formatted_filename}'")
                
                # Sanitize the formatted filename for filesystem safety (no random suffix)
                clean_filename = sanitize_title(formatted_filename, max_length=150, add_suffix=False)
                
                # Create paths for files
                thumb_path = os.path.join(content_dir, f"{clean_filename}.jpg")
                video_path = os.path.join(content_dir, f"{clean_filename}.mp4")
                json_path = os.path.join(content_dir, f"{clean_filename}.json")
                
                logger.debug(f"Final filename: {clean_filename}")
                
                # Track if we have a successful download
                video_downloaded = False
                thumbnail_downloaded = False
                
                # Download thumbnail
                try:
                    if download_thumbnail(thumbnail_url, thumb_path):
                        thumbnail_downloaded = True
                except Exception as thumb_error:
                    logger.error(f"Error downloading thumbnail: {thumb_error}")
                
                # Download video - use a separate try/except to ensure we continue even if video download fails
                try:
                    if download_video(driver, trailer_url, video_path):
                        logger.info(f"Successfully downloaded video to {video_path}")
                        video_downloaded = True
                        successful_downloads += 1
                        
                        # Flag for stopping after successful download
                        stop_after_success = video_downloaded and thumbnail_downloaded
                    else:
                        logger.error(f"Failed to download video for {metadata['title']}")
                        failed_downloads += 1
                except Exception as video_error:
                    logger.error(f"Error during video download: {video_error}")
                    failed_downloads += 1
                
                # Add file paths to metadata for reference
                metadata['download_date'] = datetime.datetime.now().isoformat()
                metadata['video_path'] = video_path
                metadata['thumbnail_path'] = thumb_path
                metadata['download_success'] = video_downloaded

                
                # Save metadata as JSON regardless of download success
                try:
                    # Ensure the directory exists
                    os.makedirs(os.path.dirname(json_path), exist_ok=True)
                    
                    # Add additional metadata
                    metadata['downloaded_date'] = datetime.datetime.now().isoformat()
                    metadata['download_success'] = video_downloaded
                    metadata['thumbnail_success'] = thumbnail_downloaded
                    metadata['source_url'] = trailer_url
                    
                    # Save the metadata to JSON
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(metadata, f, ensure_ascii=False, indent=2)
                    
                    logger.debug(f"Saved metadata to {json_path}")
                    logger.info(f"Saved metadata to {json_path}")
                    
                    # Check if we should stop after successful download (both video and thumbnail)
                    if 'stop_after_success' in locals() and stop_after_success:
                        logger.info("Both video and thumbnail downloaded successfully. Stopping script as requested.")
                        break
                except Exception as json_error:
                    logger.error(f"Error saving metadata: {json_error}")
                
            except Exception as e:
                logger.error(f"Error processing trailer {trailer_url}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                continue

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Exiting gracefully.")
    except Exception as e:
        logger.error(f"Unhandled exception in main: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        if driver:
            driver.quit()
            logger.debug("WebDriver closed.")

def download_with_ytdlp(url, filepath, aggressive=False):
    """Download video using yt-dlp as a standalone tool with option for aggressive mode."""
    try:
        # Configure YoutubeDL options
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best/mp4',  # Prefer best quality
            'outtmpl': filepath,  # Output filename template
            'retries': 10 if aggressive else 5,  # Increased retries in aggressive mode
            'fragment_retries': 30 if aggressive else 15,  # Increased fragment retries in aggressive mode
            'progress_hooks': [lambda d: logger.debug(f"yt-dlp progress: {d.get('status', 'unknown')}")],
            'quiet': False,
            'verbose': True,
            'no_warnings': False,
            'ignoreerrors': False,
            'noplaylist': True,  # Only download the video, not the playlist
            'merge_output_format': 'mp4',  # Always output as MP4
            'hls_prefer_native': False,  # Use FFmpeg for HLS
            'hls_use_mpegts': True,  # Use .ts container for HLS downloads
            'external_downloader': 'ffmpeg',  # Use ffmpeg as external downloader
            'ratelimit': 0,  # No rate limit
            'socket_timeout': 120 if aggressive else 60,  # Increased timeout in aggressive mode
            'extractor_retries': 10 if aggressive else 5,  # Increased extractor retries in aggressive mode
            'skip_download_archive': True if aggressive else False,  # Skip the download archive check in aggressive mode
            'break_on_existing': False,  # Don't stop on existing files
            'overwrites': True if aggressive else False,  # Overwrite existing files in aggressive mode
            'force_generic_extractor': aggressive,  # Try generic extractor in aggressive mode
            'external_downloader_args': {
                'ffmpeg': [
                    '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
                    '-user_agent', USER_AGENT,
                    '-analyzeduration', '30000000' if aggressive else '20000000',  # Increased analysis time in aggressive mode
                    '-probesize', '100000000' if aggressive else '50000000',  # Increased probe size in aggressive mode
                    '-reconnect', '1',
                    '-reconnect_streamed', '1',
                    '-reconnect_delay_max', '20' if aggressive else '10'
                ]
            },
            'http_headers': {
                'User-Agent': USER_AGENT,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate',
                'Referer': url
            }
        }
        
        # Create parent directory if it doesn't exist
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        # Check if file was created and has size > 0
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            logger.info(f"Successfully downloaded video using yt-dlp to {filepath}")
            return True
        else:
            logger.warning(f"yt-dlp didn't produce output file at {filepath}")
            return False
    except Exception as e:
        logger.error(f"Error downloading with yt-dlp: {e}")
        return False

def cleanup_incomplete_downloads(base_dir):
    """Scan download folders and delete any that don't have both video and thumbnail files."""
    logger.info("Starting cleanup of incomplete downloads...")
    deleted_count = 0
    kept_count = 0
    
    # Walk through all actress directories
    for actress_dir in os.listdir(base_dir):
        actress_path = os.path.join(base_dir, actress_dir)
        if not os.path.isdir(actress_path):
            continue
            
        # Walk through all video code directories for this actress
        for video_dir in os.listdir(actress_path):
            video_code_path = os.path.join(actress_path, video_dir)
            if not os.path.isdir(video_code_path):
                continue
                
            # Check if this directory has video, thumbnail, and metadata files
            has_video = False
            has_thumbnail = False
            has_metadata = False
            
            for file in os.listdir(video_code_path):
                file_path = os.path.join(video_code_path, file)
                if file.endswith('.mp4') and os.path.getsize(file_path) > 0:
                    has_video = True
                elif file.endswith('.jpg') and os.path.getsize(file_path) > 0:
                    has_thumbnail = True
                elif file.endswith('.json') and os.path.getsize(file_path) > 0:
                    has_metadata = True
            
            # If the directory doesn't have all required files (video, thumbnail, and metadata), delete it
            if not (has_video and has_thumbnail and has_metadata):
                logger.info(f"Deleting incomplete directory: {video_code_path}")
                try:
                    # Delete all files in the directory
                    for file in os.listdir(video_code_path):
                        file_path = os.path.join(video_code_path, file)
                        os.remove(file_path)
                        
                    # Delete the directory itself
                    os.rmdir(video_code_path)
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Error deleting directory {video_code_path}: {e}")
            else:
                logger.debug(f"Keeping complete directory: {video_code_path}")
                kept_count += 1
        
        # Check if the actress directory is now empty and delete if so
        try:
            if not os.listdir(actress_path):
                logger.info(f"Deleting empty actress directory: {actress_path}")
                os.rmdir(actress_path)
        except Exception as e:
            logger.error(f"Error deleting empty actress directory {actress_path}: {e}")
    
    logger.info(f"Cleanup complete. Deleted {deleted_count} incomplete directories, kept {kept_count} complete directories.")
    return deleted_count, kept_count

if __name__ == "__main__":
    main()
    # Clean up incomplete downloads after main processing
    cleanup_incomplete_downloads(DOWNLOAD_DIR)
