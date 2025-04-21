import re
import os
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def sanitize_filename(filename):
    """
    Sanitize a string to be used as a filename
    
    Args:
        filename (str): String to sanitize
        
    Returns:
        str: Sanitized filename
    """
    # Replace spaces with underscores
    s = filename.strip().replace(' ', '_')
    
    # Remove invalid characters
    s = re.sub(r'[\\/*?:"<>|]', '', s)
    
    # Limit length
    if len(s) > 50:
        s = s[:50]
    
    return s

def get_file_size(file_path):
    """
    Get the size of a file in human-readable format
    
    Args:
        file_path (str): Path to the file
        
    Returns:
        str: Human-readable file size
    """
    if not os.path.exists(file_path):
        return "0 B"
    
    size_bytes = os.path.getsize(file_path)
    
    # Convert to human-readable format
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024 or unit == 'GB':
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
