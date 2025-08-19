/* ============================================================
   Nexi Chat Application - script.js
   ------------------------------------------------------------
   Handles chat, search results, filters, mobile panels, and UI.
   Includes responsive logic for mobile vs. desktop.
   All functions are documented in English for clarity.
============================================================ */

/* ============================================================
   Global State
============================================================ */
let thread_id = null;
let timeoutHandle = null;
let previousResults = [];
let linkedPPNs = new Set();

/* =========================================================
   Mobile panel helpers: open/close state management
   ========================================================= */

// Open the filter panel (mobile overlay)
function openFilterPanel(pushHistory = true) {
    const panel = document.getElementById('filter-section');
    const other = document.getElementById('result-section');
    other.classList.remove('open');
    panel.classList.add('open');
    document.body.classList.add('panel-open');
    document.getElementById("back-chat-btn").style.display = "inline-flex"; // Show back button
    if (pushHistory) history.pushState({ panel: 'filters' }, '', '#filters');
}

// Close the filter panel
function closeFilterPanel(useHistoryBack = false) {
    const panel = document.getElementById('filter-section');
    panel.classList.remove('open');
    document.getElementById("back-chat-btn").style.display = "none"; // Hide back button
    if (!document.getElementById('result-section').classList.contains('open')) {
        document.body.classList.remove('panel-open');
    }
    if (useHistoryBack && history.state && history.state.panel === 'filters') {
        history.back();
    }
}

// Open the results panel (mobile overlay)
function openResultPanel(pushHistory = true) {
    const panel = document.getElementById('result-section');
    const other = document.getElementById('filter-section');
    other.classList.remove('open');
    panel.classList.add('open');
    document.body.classList.add('panel-open');
    document.getElementById("back-chat-btn").style.display = "inline-flex"; // Show back button
    if (pushHistory) history.pushState({ panel: 'results' }, '', '#results');
}

// Close the results panel
function closeResultPanel(useHistoryBack = false) {
    const panel = document.getElementById('result-section');
    panel.classList.remove('open');
    document.getElementById("back-chat-btn").style.display = "none"; // Hide back button
    if (!document.getElementById('filter-section').classList.contains('open')) {
        document.body.classList.remove('panel-open');
    }
    if (useHistoryBack && history.state && history.state.panel === 'results') {
        history.back();
    }
}

// Close any panel that is currently open
function closeAnyPanel() {
    const hasOpen = document.getElementById('filter-section').classList.contains('open') ||
                    document.getElementById('result-section').classList.contains('open');
    closeFilterPanel();
    closeResultPanel();
    if (hasOpen && history.state && history.state.panel) {
        history.back();
    }
}

/* =========================================================
   History management for back/forward navigation
   ========================================================= */
(function initHistory() {
    if (!history.state) {
        history.replaceState({ panel: 'chat' }, '', location.pathname);
    }
    window.addEventListener('popstate', (e) => {
        const state = e.state || { panel: 'chat' };
        const isFilters = state.panel === 'filters';
        const isResults = state.panel === 'results';
        if (isFilters) {
            openFilterPanel(false);
        } else if (isResults) {
            openResultPanel(false);
        } else {
            closeFilterPanel();
            closeResultPanel();
            document.body.classList.remove('panel-open');
        }
    });
})();

/* =========================================================
   Swipe gestures for mobile (open/close panels)
   ========================================================= */
let touchStartX = 0;
let touchStartY = 0;
let touchActivePanel = null;
const EDGE_GUTTER = 24;
const SWIPE_THRESH_X = 60;
const SWIPE_MAX_Y = 50;

// Record touch start position
function onTouchStart(e) {
    if (!e.touches || e.touches.length !== 1) return;
    const t = e.touches[0];
    touchStartX = t.clientX;
    touchStartY = t.clientY;

    const resOpen = document.getElementById('result-section').classList.contains('open');
    const filOpen = document.getElementById('filter-section').classList.contains('open');
    touchActivePanel = resOpen ? 'results' : (filOpen ? 'filters' : 'chat');
}

// Handle swipe release
function onTouchEnd(e) {
    if (!touchStartX && !touchStartY) return;

    const touch = (e.changedTouches && e.changedTouches[0]) || (e.touches && e.touches[0]);
    if (!touch) return;

    const dx = touch.clientX - touchStartX;
    const dy = touch.clientY - touchStartY;
    const absX = Math.abs(dx);
    const absY = Math.abs(dy);

    const vw = window.innerWidth;
    const nearLeftEdge = touchStartX <= EDGE_GUTTER;
    const nearRightEdge = touchStartX >= (vw - EDGE_GUTTER);

    if (absX < SWIPE_THRESH_X || absY > SWIPE_MAX_Y) {
        touchStartX = touchStartY = 0;
        return;
    }

    if (touchActivePanel === 'chat') {
        if (dx > 0 && nearLeftEdge) {
            openResultPanel();
        } else if (dx < 0 && nearRightEdge) {
            openFilterPanel();
        }
    } else if (touchActivePanel === 'results') {
        if (dx < 0) {
            closeResultPanel(true);
        }
    } else if (touchActivePanel === 'filters') {
        if (dx > 0) {
            closeFilterPanel(true);
        }
    }

    touchStartX = touchStartY = 0;
}
document.addEventListener('touchstart', onTouchStart, { passive: true });
document.addEventListener('touchend', onTouchEnd, { passive: true });

/* =========================================================
   Chat input handling (send, filters, etc.)
   ========================================================= */

// Enable/disable buttons depending on input state
function checkInput() {
    const userInput = document.getElementById('user-input').value.trim();
    const sendButton = document.getElementById('send-button');
    const applyFiltersButton = document.getElementById('apply-filters-button');
    const checkboxes = document.querySelectorAll('#filters input[type="checkbox"]');
    let anyChecked = Array.from(checkboxes).some(checkbox => checkbox.checked);

    sendButton.disabled = userInput === "";
    sendButton.style.backgroundColor = userInput === "" ? "#ccc" : "#6d5ab0";
    sendButton.style.cursor = userInput === "" ? "not-allowed" : "pointer";

    applyFiltersButton.disabled = !anyChecked;
    applyFiltersButton.style.backgroundColor = anyChecked ? "#6d5ab0" : "#ccc";
    applyFiltersButton.style.cursor = anyChecked ? "pointer" : "not-allowed";
}

// Update the state of action buttons (results + filters)
function updateActionButtons() {
    const resultsBtn = document.getElementById('open-results-btn');
    const filtersBtn = document.getElementById('open-filters-btn');
    const hasResults = Array.isArray(previousResults) && previousResults.length > 0;

    if (resultsBtn) resultsBtn.disabled = !hasResults;
    if (filtersBtn)  filtersBtn.disabled  = !hasResults;
}

/* =========================================================
   Thread + messaging with backend
   ========================================================= */

// Start a new OpenAI thread (server call)
async function startThread() {
    const response = await fetch('/start_thread', { method: 'POST' });
    const data = await response.json();
    thread_id = data.thread_id;
}

// Send user message to backend
async function sendMessage() {
    const userInput = document.getElementById('user-input').value.trim();
    if (userInput === "") return;

    displayUserMessage(userInput);
    showLoader();

    document.getElementById('user-input').value = '';
    checkInput();

    document.getElementById('search-results').style.display = 'grid';
    document.getElementById('detail-container').style.display = 'none';
    document.getElementById('breadcrumbs').innerHTML = '';

    timeoutHandle = setTimeout(() => { showErrorMessage(); }, 30000);

    try {
        const response = await fetch('/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                thread_id: thread_id,
                user_input: userInput,
                assistant_id: 'asst_ejPRaNkIhjPpNHDHCnoI5zKY'
            })
        });
        if (!response.ok) {
            showErrorMessage();
            return;
        }
        const data = await response.json();
        hideLoader();
        clearTimeout(timeoutHandle);

        // Agenda type response
        if (data.response && data.response.type === 'agenda') {
            if (data.response.url) {
                displayAssistantMessage(`<a href="${data.response.url}" target="_blank">${data.response.url}</a>`);
            }
            if (data.response.message) {
                displayAssistantMessage(data.response.message);
            }
            previousResults = data.response.results || [];
            displayAgendaResults(previousResults);
            await sendStatusKlaar();
            return;
        }

        // Plain response (no results)
        if (!data.response?.results) {
            displayAssistantMessage(data.response);
        }

        if (data.thread_id) {
            thread_id = data.thread_id;
        }

        // Book search results
        if (data.response?.results) {
            previousResults = data.response.results;
            displaySearchResults(previousResults);
            await sendStatusKlaar();
        }

        resetFilters();
    } catch (error) {
        showErrorMessage();
    }

    checkInput();
    scrollToBottom();
}
/* =========================================================
   Reset / status handling
   ========================================================= */

// Reset entire conversation thread
function resetThread() {
    startThread();
    document.getElementById('messages').innerHTML = '';
    document.getElementById('search-results').innerHTML = '';
    document.getElementById('breadcrumbs').innerHTML = 'results';
    document.getElementById('user-input').placeholder = "What book are you searching for? Or info about..?";
    addOpeningMessage();
    addPlaceholders();
    scrollToBottom();
    resetFilters();
    linkedPPNs.clear();
    updateActionButtons();
}

// Notify backend that status is complete
async function sendStatusKlaar() {
    try {
        const response = await fetch('/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                thread_id: thread_id,
                user_input: 'STATUS : KLAAR',
                assistant_id: 'asst_ejPRaNkIhjPpNHDHCnoI5zKY'
            })
        });
        const data = await response.json();
        displayAssistantMessage(data.response);
        scrollToBottom();
    } catch (error) {}
}

/* =========================================================
   Rendering messages + results
   ========================================================= */

// Show user message in chat
function displayUserMessage(message) {
    const messageContainer = document.getElementById('messages');
    const messageElement = document.createElement('div');
    messageElement.classList.add('user-message');
    messageElement.textContent = message;
    messageContainer.appendChild(messageElement);
    scrollToBottom();
}

// Show assistant message in chat
function displayAssistantMessage(message) {
    const messageContainer = document.getElementById('messages');
    const messageElement = document.createElement('div');
    messageElement.classList.add('assistant-message');
    if (typeof message === 'object') {
        messageElement.textContent = JSON.stringify(message);
    } else {
        messageElement.innerHTML = message;
    }
    messageContainer.appendChild(messageElement);
    scrollToBottom();
}

// Show search results (books grid)
function displaySearchResults(results) {
    const searchResultsContainer = document.getElementById('search-results');
    searchResultsContainer.classList.remove('agenda-list');
    searchResultsContainer.classList.add('book-grid');
    searchResultsContainer.innerHTML = '';

    results.forEach(result => {
        const resultElement = document.createElement('div');
        resultElement.classList.add('search-result');
        resultElement.innerHTML = `
            <div onclick="fetchAndShowDetailPage('${result.ppn}')">
                <img src="https://cover.biblion.nl/coverlist.dll/?doctype=morebutton&bibliotheek=oba&style=0&ppn=${result.ppn}&isbn=&lid=&aut=&ti=&size=150" 
                     alt="Cover for PPN ${result.ppn}" 
                     class="book-cover">
                <p>${result.short_title}</p>
            </div>
        `;
        searchResultsContainer.appendChild(resultElement);
    });

    updateResultsBadge(results.length);
    updateActionButtons();
}

// Show agenda results (events list)
function displayAgendaResults(results) {
    const searchResultsContainer = document.getElementById('search-results');
    searchResultsContainer.innerHTML = '';
    searchResultsContainer.classList.remove('book-grid');
    searchResultsContainer.classList.add('agenda-list');

    const maxItems = 5;
    const limitedResults = results.slice(0, maxItems);

    limitedResults.forEach(result => {
        let formattedDate = result.date || 'Date not available';
        let formattedTime = result.time || '';

        if ((!formattedDate || !formattedTime) && result.raw_date && result.raw_date.start) {
            const startDate = new Date(result.raw_date.start);
            formattedDate = formattedDate || startDate.toLocaleDateString('nl-NL', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
            formattedTime = formattedTime || startDate.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' });
        }
        if ((!formattedTime) && result.raw_date && result.raw_date.end) {
            const endDate = new Date(result.raw_date.end);
            formattedTime = (formattedTime ? (formattedTime + ' - ') : '') + endDate.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' });
        }

        const location = result.location || 'Location not available';
        const title = result.title || 'No title available';
        const summary = result.summary || 'No description available';
        const coverImage = result.cover || '';
        const link = result.link || '#';

        const el = document.createElement('div');
        el.classList.add('agenda-card');
        el.innerHTML = `
            <a href="${link}" target="_blank" class="agenda-card-link">
                <img src="${coverImage}" alt="Agenda cover" class="agenda-card-image">
                <div class="agenda-card-text">
                    <div class="agenda-date">${formattedDate}</div>
                    <div class="agenda-time">${formattedTime}</div>
                    <div class="agenda-title">${title}</div>
                    <div class="agenda-location">${location}</div>
                    <div class="agenda-summary">${summary}</div>
                </div>
            </a>
        `;
        searchResultsContainer.appendChild(el);
    });

    if (results.length > maxItems) {
        const moreButton = document.createElement('button');
        moreButton.classList.add('more-button');
        moreButton.innerHTML = 'More';
        moreButton.onclick = () => {
            const url = results[0].link || '#';
            window.open(url, '_blank');
        };
        searchResultsContainer.appendChild(moreButton);
    }

    updateResultsBadge(results.length);
    updateActionButtons();
}

// Update result badge (bubble with count)
function updateResultsBadge(count) {
    const badge = document.getElementById('results-badge');
    const btn = document.getElementById('open-results-btn');
    if (!badge || !btn) return;

    badge.textContent = count;
    badge.style.display = count > 0 ? 'inline-block' : 'none';

    if (count > 0) {
        btn.classList.add('enlarged');
        setTimeout(() => {
            btn.classList.remove('enlarged');
        }, 2000);
    }
}

/* =========================================================
   Detail view handling
   ========================================================= */

// Show agenda detail (event view)
function showAgendaDetail(result) {
    const detailContainer = document.getElementById('detail-container');
    detailContainer.innerHTML = `
        <div class="detail-container">
            <img src="${result.cover}" alt="Agenda cover" class="detail-cover">
            <div class="detail-summary">
                <h3>${result.title}</h3>
                <div class="detail-buttons">
                    <button onclick="window.open('${result.link}', '_blank')">View on OBA.nl</button>
                </div>
            </div>
        </div>
    `;
    detailContainer.style.display = 'flex';
}

// Fetch and display detail page for a specific PPN (book)
async function fetchAndShowDetailPage(ppn) {
    try {
        const resolverResponse = await fetch(`/proxy/resolver?ppn=${ppn}`);
        const resolverText = await resolverResponse.text();
        const parser = new DOMParser();
        const resolverDoc = parser.parseFromString(resolverText, "application/xml");
        const itemIdElement = resolverDoc.querySelector('itemid');
        if (!itemIdElement) {
            throw new Error('Item ID not found in resolver response.');
        }
        const itemId = itemIdElement.textContent.split('|')[2];

        const detailResponse = await fetch(`/proxy/details?item_id=${itemId}`);
        const contentType = detailResponse.headers.get("content-type");
        if (contentType && contentType.indexOf("application/json") !== -1) {
            const detailJson = await detailResponse.json();

            const title = detailJson.record.titles[0] || 'Title not available';
            const summary = detailJson.record.summaries[0] || 'Summary not available';
            const coverImage = detailJson.record.coverimages[0] || '';

            const detailContainer = document.getElementById('detail-container');
            const searchResultsContainer = document.getElementById('search-results');
            
            searchResultsContainer.style.display = 'none';
            detailContainer.style.display = 'block';

            detailContainer.innerHTML = `
                <div class="detail-container">
                    <img src="${coverImage}" alt="Cover for PPN ${ppn}" class="detail-cover">
                    <div class="detail-summary">
                        <p>${summary}</p>
                        <div class="detail-buttons">
                            <button onclick="goBackToResults()">Back</button>
                            <button onclick="window.open('https://oba.nl/nl/collectie/oba-collectie?id=' + encodeURIComponent('|oba-catalogus|' + '${itemId}'), '_blank')">More info on OBA.nl</button>
                            <button onclick="window.open('https://iguana.oba.nl/iguana/www.main.cls?sUrl=search&theme=OBA#app=Reserve&ppn=${ppn}', '_blank')">Reserve</button>
                        </div>
                    </div>
                </div>
            `;

            const currentUrl = window.location.href.split('?')[0];
            const breadcrumbs = document.getElementById('breadcrumbs');
            breadcrumbs.innerHTML = `<a href="#" onclick="goBackToResults()">results</a> > <span class="breadcrumb-title"><a href="${currentUrl}?ppn=${ppn}" target="_blank">${title}</a></span>`;
            
            if (!linkedPPNs.has(ppn)) {
                sendDetailPageLinkToUser(title, currentUrl, ppn);
            }
        } else {
            throw new Error('Unexpected response content type');
        }
    } catch (error) {
        displayAssistantMessage('Something went wrong while fetching the detail page.');
    }
}

// Return to results from detail view
function goBackToResults() {
    const detailContainer = document.getElementById('detail-container');
    const searchResultsContainer = document.getElementById('search-results');
    detailContainer.style.display = 'none';
    searchResultsContainer.style.display = 'grid';
    displaySearchResults(previousResults);
    document.getElementById('breadcrumbs').innerHTML = '';
}

// Send link of detail page to chat
function sendDetailPageLinkToUser(title, baseUrl, ppn) {
    if (linkedPPNs.has(ppn)) return;
    const message = `Title: <a href="#" onclick="fetchAndShowDetailPage('${ppn}'); return false;">${title}</a>`;
    displayAssistantMessage(message);
    linkedPPNs.add(ppn);
}
/* =========================================================
   Filters handling
   ========================================================= */

// Apply filters and trigger search
async function applyFiltersAndSend() {
    const checkboxes = document.querySelectorAll('#filters input[type="checkbox"]');
    let selectedFilters = [];
    checkboxes.forEach(checkbox => {
        if (checkbox.checked) {
            selectedFilters.push(checkbox.value);
        }
    });
    const filterString = selectedFilters.join('||');
    if (filterString === "") return;

    displayUserMessage(`Filters applied: ${filterString}`);
    showLoader();

    document.getElementById('search-results').style.display = 'grid';
    document.getElementById('detail-container').style.display = 'none';
    document.getElementById('breadcrumbs').innerHTML = '';

    try {
        const response = await fetch('/apply_filters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                thread_id: thread_id,
                filter_values: filterString,
                assistant_id: 'asst_ejPRaNkIhjPpNHDHCnoI5zKY'
            })
        });

        if (!response.ok) {
            hideLoader();
            return;
        }

        const data = await response.json();
        hideLoader();

        if (data.response && data.response.type === 'agenda') {
            previousResults = data.response.results || [];
            displayAgendaResults(previousResults);
            await sendStatusKlaar();
        } else if (data.results) {
            previousResults = data.results;
            displaySearchResults(previousResults);
            await sendStatusKlaar();
        }

        if (data.thread_id) {
            thread_id = data.thread_id;
        }

        closeFilterPanel(true);
        resetFilters();
    } catch (error) {
        hideLoader();
    }

    checkInput();
}

// Clear filter checkboxes
function resetFilters() {
    const checkboxes = document.querySelectorAll('#filters input[type="checkbox"]');
    checkboxes.forEach(checkbox => { checkbox.checked = false; });
    checkInput();
}

/* =========================================================
   Loader (typing indicator)
   ========================================================= */

// Show loader animation while waiting for response
function showLoader() {
    const messageContainer = document.getElementById('messages');
    const loaderElement = document.createElement('div');
    loaderElement.classList.add('assistant-message', 'loader');
    loaderElement.id = 'loader';
    loaderElement.innerHTML = '<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span>';
    messageContainer.appendChild(loaderElement);
    scrollToBottom();
}

// Hide loader
function hideLoader() {
    const loaderElement = document.getElementById('loader');
    if (loaderElement) { loaderElement.remove(); }
    const sendButton = document.getElementById('send-button');
    sendButton.disabled = false;
    sendButton.style.backgroundColor = "#6d5ab0";
    sendButton.style.cursor = "pointer";
}

/* =========================================================
   Chat utilities
   ========================================================= */

// Auto-scroll chat to bottom
function scrollToBottom() {
    const messageContainer = document.getElementById('messages');
    messageContainer.scrollTop = messageContainer.scrollHeight;
}

// Add opening message to chat
function addOpeningMessage() {
    const openingMessage = "Hi! I’m Nexi, I’ll help you search for books and information in the OBA. For example: 'books like World Spies' or 'do you have information about sea mammals?'";
    const messageContainer = document.getElementById('messages');
    const messageElement = document.createElement('div');
    messageElement.classList.add('assistant-message');
    messageElement.textContent = openingMessage;
    messageContainer.appendChild(messageElement);
    scrollToBottom();
}

// Add placeholder covers in results
function addPlaceholders() {
    const searchResultsContainer = document.getElementById('search-results');
    searchResultsContainer.innerHTML = `
        <div><img src="/static/images/placeholder.png" alt="Placeholder"></div>
        <div><img src="/static/images/placeholder.png" alt="Placeholder"></div>
        <div><img src="/static/images/placeholder.png" alt="Placeholder"></div>
        <div><img src="/static/images/placeholder.png" alt="Placeholder"></div>
    `;
}

// Show error message and reset state
function showErrorMessage() {
    displayAssistantMessage('Something went wrong, restarting...');
    hideLoader();
    clearTimeout(timeoutHandle);
    resetThread();
    updateActionButtons();
    setTimeout(() => { clearErrorMessage(); }, 2000);
}

// Clear error message
function clearErrorMessage() {
    const messageContainer = document.getElementById('messages');
    const lastMessage = messageContainer.lastChild;
    if (lastMessage && lastMessage.textContent.includes('Something went wrong')) {
        messageContainer.removeChild(lastMessage);
    }
}

/* =========================================================
   Initialization
   ========================================================= */

// Event listeners for input + filters
document.getElementById('user-input').addEventListener('input', function() {
    checkInput();
    if (this.value !== "") this.placeholder = "";
});
document.getElementById('user-input').addEventListener('keypress', function(event) {
    if (event.key === 'Enter') sendMessage();
});
document.querySelectorAll('#filters input[type="checkbox"]').forEach(checkbox => {
    checkbox.addEventListener('change', checkInput);
});

// Initial setup when page loads
window.onload = async () => {
    await startThread();
    addOpeningMessage();
    addPlaceholders();
    checkInput();
    document.getElementById('user-input').placeholder = "Tell me what you are looking for!";
    const applyFiltersButton = document.querySelector('button[onclick="applyFiltersAndSend()"]');
    if (applyFiltersButton) applyFiltersButton.onclick = applyFiltersAndSend;
    resetFilters();
    linkedPPNs.clear();
    closeFilterPanel();
    closeResultPanel();
    if (!history.state) history.replaceState({ panel: 'chat' }, '', location.pathname);
    updateActionButtons();
};

