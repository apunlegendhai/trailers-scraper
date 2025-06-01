import json

# Simple example scraper that returns mock data
def scrape():
    # Mock data for demonstration
    data = [
        {
            "title": "Example Item 1",
            "description": "This is a sample scraped item"
        },
        {
            "title": "Example Item 2",
            "description": "Another sample scraped item"
        }
    ]
    return data

if __name__ == "__main__":
    # Print the results as JSON so the Node.js server can parse it
    print(json.dumps(scrape()))