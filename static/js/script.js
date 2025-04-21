// Global variables to track state
let currentActress = '';
let currentPage = 1;
let isLoading = false;
let hasMoreResults = true;

// DOM Elements
const actressInput = document.getElementById('actress-name');
const searchBtn = document.getElementById('search-btn');
const randomBtn = document.getElementById('random-btn');
const loadMoreBtn = document.getElementById('load-more-btn');
const resultsContainer = document.getElementById('results-container');
const resultsGrid = document.getElementById('results-grid');
const resultsCount = document.getElementById('results-count');
const noResultsMessage = document.getElementById('no-results-message');
const statusContainer = document.getElementById('status-container');
const downloadStatus = document.getElementById('download-status');
const statusMessage = document.getElementById('status-message');
const downloadDetails = document.getElementById('download-details');
const downloadActress = document.getElementById('download-actress');
const downloadCode = document.getElementById('download-code');
const downloadTrailer = document.getElementById('download-trailer');
const downloadThumbnail = document.getElementById('download-thumbnail');
const downloadScreenshots = document.getElementById('download-screenshots');
const downloadDirectory = document.getElementById('download-directory');

// Initialize tooltips
document.addEventListener('DOMContentLoaded', function() {
    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
});

// Event Listeners
searchBtn.addEventListener('click', () => {
    const actressName = actressInput.value.trim();
    if (actressName) {
        currentActress = actressName;
        currentPage = 1;
        hasMoreResults = true;
        searchVideos(actressName, 1, true);
    } else {
        showAlert('Please enter an actress name', 'warning');
    }
});

actressInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        searchBtn.click();
    }
});

randomBtn.addEventListener('click', () => {
    const actressName = actressInput.value.trim();
    if (actressName) {
        downloadRandomVideo(actressName);
    } else {
        showAlert('Please enter an actress name', 'warning');
    }
});

loadMoreBtn.addEventListener('click', () => {
    if (!isLoading && hasMoreResults) {
        currentPage++;
        searchVideos(currentActress, currentPage, false);
    }
});

// Functions
async function searchVideos(actressName, page, clearResults) {
    if (isLoading) return;

    setLoading(true);

    try {
        // Show results container
        resultsContainer.classList.remove('d-none');

        // Clear previous results if needed
        if (clearResults) {
            resultsGrid.innerHTML = '';
            noResultsMessage.classList.add('d-none');
        }

        // Make API request
        const response = await fetch('/search', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ actress_name: actressName, page: page })
        });

        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Unknown error occurred');
        }

        // Handle results
        if (data.videos && data.videos.length > 0) {
            // Update results count
            resultsCount.textContent = `${data.videos.length} videos`;

            // Render videos
            renderVideos(data.videos);

            // If no videos returned, assume no more pages
            if (data.videos.length < 10) {
                hasMoreResults = false;
                loadMoreBtn.classList.add('disabled');
                loadMoreBtn.textContent = 'No More Results';
            } else {
                loadMoreBtn.classList.remove('disabled');
                loadMoreBtn.textContent = 'Load More';
            }
        } else {
            // No results
            hasMoreResults = false;
            loadMoreBtn.classList.add('disabled');
            loadMoreBtn.textContent = 'No More Results';

            if (clearResults) {
                noResultsMessage.classList.remove('d-none');
            }
        }
    } catch (error) {
        console.error('Error searching videos:', error);
        showAlert(`Error: ${error.message}`, 'danger');
    } finally {
        setLoading(false);
    }
}

function renderVideos(videos) {
    const template = document.getElementById('result-template');

    videos.forEach(video => {
        // Clone template
        const clone = document.importNode(template.content, true);

        // Set content
        const thumbnail = clone.querySelector('.result-thumbnail');
        const title = clone.querySelector('.result-title');
        const downloadBtn = clone.querySelector('.download-btn');

        thumbnail.src = video.thumbnail;
        thumbnail.alt = video.title;
        title.textContent = video.title;

        // Set up download button
        downloadBtn.addEventListener('click', () => {
            downloadVideo(video.url, currentActress);
        });

        // Append to grid
        resultsGrid.appendChild(clone);
    });
}

async function downloadVideo(videoUrl, actressName) {
    if (isLoading) return;

    // Show status container
    statusContainer.classList.remove('d-none');
    downloadDetails.classList.add('d-none');
    downloadStatus.classList.remove('alert-success', 'alert-danger');
    downloadStatus.classList.add('alert-info');
    statusMessage.textContent = 'Downloading video...';

    setLoading(true);

    try {
        // Make API request
        const response = await fetch('/download', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ video_url: videoUrl, actress_name: actressName })
        });

        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Unknown error occurred');
        }

        // Update status
        downloadStatus.classList.remove('alert-info', 'alert-danger');
        downloadStatus.classList.add('alert-success');
        statusMessage.textContent = data.message || 'Download completed successfully';

        // Show details
        displayDownloadDetails(data.details, actressName);
    } catch (error) {
        console.error('Error downloading video:', error);
        downloadStatus.classList.remove('alert-info', 'alert-success');
        downloadStatus.classList.add('alert-danger');
        statusMessage.textContent = `Error: ${error.message || 'Failed to download. Please try again.'}`;
    } finally {
        setLoading(false);
    }
}

async function downloadRandomVideo(actressName) {
    if (isLoading) return;

    // Show status container
    statusContainer.classList.remove('d-none');
    downloadDetails.classList.add('d-none');
    downloadStatus.classList.remove('alert-success', 'alert-danger');
    downloadStatus.classList.add('alert-info');
    statusMessage.textContent = 'Finding and downloading a random video...';

    setLoading(true);

    try {
        // Make API request
        const response = await fetch('/download_random', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ actress_name: actressName })
        });

        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Unknown error occurred');
        }

        // Update status
        downloadStatus.classList.remove('alert-info', 'alert-danger');
        downloadStatus.classList.add('alert-success');
        statusMessage.textContent = `Downloaded: ${data.video_title || 'Random video'}`;

        // Show details
        displayDownloadDetails(data.details, actressName);
    } catch (error) {
        console.error('Error downloading random video:', error);
        downloadStatus.classList.remove('alert-info', 'alert-success');
        downloadStatus.classList.add('alert-danger');
        statusMessage.textContent = `Error: ${error.message || 'Failed to download. Please try again.'}`;
    } finally {
        setLoading(false);
    }
}

function displayDownloadDetails(details, actressName) {
    if (!details || !details.summary) return;

    // Show details container
    downloadDetails.classList.remove('d-none');

    // Fill in details
    downloadActress.textContent = actressName;
    downloadCode.textContent = details.summary.video_code || 'Unknown';

    // Trailer status
    downloadTrailer.className = 'badge rounded-pill';
    downloadTrailer.classList.add(details.trailer ? 'bg-success' : 'bg-danger');
    downloadTrailer.textContent = details.trailer ? 'Downloaded' : 'Failed';

    // Thumbnail status
    downloadThumbnail.className = 'badge rounded-pill';
    downloadThumbnail.classList.add(details.thumbnail ? 'bg-success' : 'bg-danger');
    downloadThumbnail.textContent = details.thumbnail ? 'Downloaded' : 'Failed';

    // Screenshots status
    const totalScreenshots = details.summary.total_screenshots || 0;
    const successfulScreenshots = details.summary.successful_screenshots || 0;
    downloadScreenshots.textContent = `${successfulScreenshots}/${totalScreenshots}`;

    if (successfulScreenshots === 0) {
        downloadScreenshots.className = 'badge rounded-pill bg-danger';
    } else if (successfulScreenshots < totalScreenshots) {
        downloadScreenshots.className = 'badge rounded-pill bg-warning';
    } else {
        downloadScreenshots.className = 'badge rounded-pill bg-success';
    }

    // Directory
    downloadDirectory.textContent = details.summary.directory || 'Unknown location';
}

function setLoading(loading) {
    isLoading = loading;

    // Update UI elements
    searchBtn.disabled = loading;
    randomBtn.disabled = loading;
    loadMoreBtn.disabled = loading;

    if (loading) {
        searchBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Searching...';
        loadMoreBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading...';
    } else {
        searchBtn.innerHTML = 'Search';
        loadMoreBtn.innerHTML = hasMoreResults ? 'Load More' : 'No More Results';
    }
}

function showAlert(message, type = 'info') {
    // Create alert element
    const alertEl = document.createElement('div');
    alertEl.className = `alert alert-${type} alert-dismissible fade show`;
    alertEl.setAttribute('role', 'alert');
    alertEl.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;

    // Insert at top of page
    document.querySelector('.container').prepend(alertEl);

    // Auto dismiss after 5 seconds
    setTimeout(() => {
        const bsAlert = new bootstrap.Alert(alertEl);
        bsAlert.close();
    }, 5000);
}