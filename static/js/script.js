let thread_id = null;
let timeoutHandle = null;
let previousResults = [];
let linkedPPNs = new Set();

/* ===== Mobiele helpers: panel state, overlay, history ===== */
function openFilterPanel(pushHistory = true) {
    const panel = document.getElementById('filter-section');
    const other = document.getElementById('result-section');
    other.classList.remove('open');
    panel.classList.add('open');
    document.body.classList.add('panel-open');
    if (pushHistory) history.pushState({ panel: 'filters' }, '', '#filters');
}
function closeFilterPanel(useHistoryBack = false) {
    const panel = document.getElementById('filter-section');
    panel.classList.remove('open');
    if (!document.getElementById('result-section').classList.contains('open')) {
        document.body.classList.remove('panel-open');
    }
    if (useHistoryBack && history.state && history.state.panel === 'filters') {
        history.back();
    }
}
function openResultPanel(pushHistory = true) {
    const panel = document.getElementById('result-section');
    const other = document.getElementById('filter-section');
    other.classList.remove('open');
    panel.classList.add('open');
    document.body.classList.add('panel-open');
    if (pushHistory) history.pushState({ panel: 'results' }, '', '#results');
}
function closeResultPanel(useHistoryBack = false) {
    const panel = document.getElementById('result-section');
    panel.classList.remove('open');
    if (!document.getElementById('filter-section').classList.contains('open')) {
        document.body.classList.remove('panel-open');
    }
    if (useHistoryBack && history.state && history.state.panel === 'results') {
        history.back();
    }
}
function closeAnyPanel() {
    const hasOpen = document.getElementById('filter-section').classList.contains('open') ||
                    document.getElementById('result-section').classList.contains('open');
    closeFilterPanel();
    closeResultPanel();
    if (hasOpen && history.state && history.state.panel) {
        history.back();
    }
}

/* History: initial state + popstate handler */
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

/* Swipe-gestures (mobiel) */
let touchStartX = 0;
let touchStartY = 0;
let touchActivePanel = null;
const EDGE_GUTTER = 24;
const SWIPE_THRESH_X = 60;
const SWIPE_MAX_Y = 50;

function onTouchStart(e) {
    if (!e.touches || e.touches.length !== 1) return;
    const t = e.touches[0];
    touchStartX = t.clientX;
    touchStartY = t.clientY;

    const resOpen = document.getElementById('result-section').classList.contains('open');
    const filOpen = document.getElementById('filter-section').classList.contains('open');
    touchActivePanel = resOpen ? 'results' : (filOpen ? 'filters' : 'chat');
}
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

/* ===== Functionaliteit chat en zoekresultaten ===== */
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

async function startThread() {
    const response = await fetch('/start_thread', { method: 'POST' });
    const data = await response.json();
    thread_id = data.thread_id;
}

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

        if (!data.response?.results) {
            displayAssistantMessage(data.response);
        }

        if (data.thread_id) {
            thread_id = data.thread_id;
        }

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

function resetThread() {
    startThread();
    document.getElementById('messages').innerHTML = '';
    document.getElementById('search-results').innerHTML = '';
    document.getElementById('breadcrumbs').innerHTML = 'resultaten';
    document.getElementById('user-input').placeholder = "Welk boek zoek je? Of informatie over..?";
    addOpeningMessage();
    addPlaceholders();
    scrollToBottom();
    resetFilters();
    linkedPPNs.clear();
}

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

function displayUserMessage(message) {
    const messageContainer = document.getElementById('messages');
    const messageElement = document.createElement('div');
    messageElement.classList.add('user-message');
    messageElement.textContent = message;
    messageContainer.appendChild(messageElement);
    scrollToBottom();
}

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
}

function displayAgendaResults(results) {
    const searchResultsContainer = document.getElementById('search-results');
    searchResultsContainer.innerHTML = '';
    searchResultsContainer.classList.remove('book-grid');
    searchResultsContainer.classList.add('agenda-list');

    const maxItems = 5;
    const limitedResults = results.slice(0, maxItems);

    limitedResults.forEach(result => {
        let formattedDate = result.date || 'Datum niet beschikbaar';
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

        const location = result.location || 'Locatie niet beschikbaar';
        const title = result.title || 'Geen titel beschikbaar';
        const summary = result.summary || 'Geen beschrijving beschikbaar';
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
        moreButton.innerHTML = 'Meer';
        moreButton.onclick = () => {
            const url = results[0].link || '#';
            window.open(url, '_blank');
        };
        searchResultsContainer.appendChild(moreButton);
    }

    updateResultsBadge(results.length);
}

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

function showAgendaDetail(result) {
    const detailContainer = document.getElementById('detail-container');
    detailContainer.innerHTML = `
        <div class="detail-container">
            <img src="${result.cover}" alt="Agenda cover" class="detail-cover">
            <div class="detail-summary">
                <h3>${result.title}</h3>
                <div class="detail-buttons">
                    <button onclick="window.open('${result.link}', '_blank')">Bekijk op OBA.nl</button>
                </div>
            </div>
        </div>
    `;
    detailContainer.style.display = 'flex';
}

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

            const title = detailJson.record.titles[0] || 'Titel niet beschikbaar';
            const summary = detailJson.record.summaries[0] || 'Samenvatting niet beschikbaar';
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
                            <button onclick="goBackToResults()">Terug</button>
                            <button onclick="window.open('https://oba.nl/nl/collectie/oba-collectie?id=' + encodeURIComponent('|oba-catalogus|' + '${itemId}'), '_blank')">Meer informatie op OBA.nl</button>
                            <button onclick="window.open('https://iguana.oba.nl/iguana/www.main.cls?sUrl=search&theme=OBA#app=Reserve&ppn=${ppn}', '_blank')">Reserveer</button>
                        </div>
                    </div>
                </div>
            `;

            const currentUrl = window.location.href.split('?')[0];
            const breadcrumbs = document.getElementById('breadcrumbs');
            breadcrumbs.innerHTML = `<a href="#" onclick="goBackToResults()">resultaten</a> > <span class="breadcrumb-title"><a href="${currentUrl}?ppn=${ppn}" target="_blank">${title}</a></span>`;
            
            if (!linkedPPNs.has(ppn)) {
                sendDetailPageLinkToUser(title, currentUrl, ppn);
            }
        } else {
            throw new Error('Unexpected response content type');
        }
    } catch (error) {
        displayAssistantMessage('Er is iets misgegaan bij het ophalen van de detailpagina.');
    }
}

function goBackToResults() {
    const detailContainer = document.getElementById('detail-container');
    const searchResultsContainer = document.getElementById('search-results');
    detailContainer.style.display = 'none';
    searchResultsContainer.style.display = 'grid';
    displaySearchResults(previousResults);
    document.getElementById('breadcrumbs').innerHTML = '';
}

function sendDetailPageLinkToUser(title, baseUrl, ppn) {
    if (linkedPPNs.has(ppn)) return;
    const message = `Titel: <a href="#" onclick="fetchAndShowDetailPage('${ppn}'); return false;">${title}</a>`;
    displayAssistantMessage(message);
    linkedPPNs.add(ppn);
}

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

    displayUserMessage(`Filters toegepast: ${filterString}`);
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

function startNewChat() {
    startThread();
    document.getElementById('messages').innerHTML = '';
    document.getElementById('search-results').innerHTML = '';
    document.getElementById('detail-container').style.display = 'none';
    document.getElementById('breadcrumbs').innerHTML = 'resultaten';
    document.getElementById('user-input').placeholder = "Welk boek zoek je? Of informatie over..?";
    addOpeningMessage();
    addPlaceholders();
    scrollToBottom();
    resetFilters();
    linkedPPNs.clear();
}

async function startHelpThread() {
    await startThread();
    document.getElementById('messages').innerHTML = '';
    document.getElementById('search-results').innerHTML = '';
    document.getElementById('breadcrumbs').innerHTML = 'resultaten';
    resetFilters();
    linkedPPNs.clear();
    addPlaceholders();
    addOpeningMessage();
    const userMessage = "help";
    displayUserMessage(userMessage);
    await sendHelpMessage(userMessage);
}

async function sendHelpMessage(message) {
    showLoader();
    try {
        const response = await fetch('/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                thread_id: thread_id,
                user_input: message,
                assistant_id: 'asst_ejPRaNkIhjPpNHDHCnoI5zKY'
            })
        });
        if (!response.ok) {
            throw new Error('Het verzenden van het help-bericht is mislukt.');
        }
        const data = await response.json();
        hideLoader();
        if (data.response) {
            displayAssistantMessage(data.response);
        }
    } catch (error) {
        hideLoader();
        displayAssistantMessage('Er is iets misgegaan. Probeer opnieuw.');
    }
}

function extractSearchQuery(response) {
    const searchMarker = "SEARCH_QUERY:";
    if (response.includes(searchMarker)) {
        return response.split(searchMarker)[1].trim();
    }
    return null;
}

function resetFilters() {
    const checkboxes = document.querySelectorAll('#filters input[type="checkbox"]');
    checkboxes.forEach(checkbox => { checkbox.checked = false; });
    checkInput();
}

function showLoader() {
    const messageContainer = document.getElementById('messages');
    const loaderElement = document.createElement('div');
    loaderElement.classList.add('assistant-message', 'loader');
    loaderElement.id = 'loader';
    loaderElement.innerHTML = '<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span>';
    messageContainer.appendChild(loaderElement);
    scrollToBottom();
}

function hideLoader() {
    const loaderElement = document.getElementById('loader');
    if (loaderElement) { loaderElement.remove(); }
    const sendButton = document.getElementById('send-button');
    sendButton.disabled = false;
    sendButton.style.backgroundColor = "#6d5ab0";
    sendButton.style.cursor = "pointer";
}

function scrollToBottom() {
    const messageContainer = document.getElementById('messages');
    messageContainer.scrollTop = messageContainer.scrollHeight;
}

function addOpeningMessage() {
    const openingMessage = "Hoi! Ik ben Nexi, ik help je zoeken naar boeken en informatie in de OBA. Bijvoorbeeld: 'boeken die lijken op Wereldspionnen' of 'heb je informatie over zeezoogdieren?'";
    const messageContainer = document.getElementById('messages');
    const messageElement = document.createElement('div');
    messageElement.classList.add('assistant-message');
    messageElement.textContent = openingMessage;
    messageContainer.appendChild(messageElement);
    scrollToBottom();
}

function addPlaceholders() {
    const searchResultsContainer = document.getElementById('search-results');
    searchResultsContainer.innerHTML = `
        <div><img src="/static/images/placeholder.png" alt="Placeholder"></div>
        <div><img src="/static/images/placeholder.png" alt="Placeholder"></div>
        <div><img src="/static/images/placeholder.png" alt="Placeholder"></div>
        <div><img src="/static/images/placeholder.png" alt="Placeholder"></div>
    `;
}

function showErrorMessage() {
    displayAssistantMessage('er is iets misgegaan, we beginnen opnieuw');
    hideLoader();
    clearTimeout(timeoutHandle);
    resetThread();
    setTimeout(() => { clearErrorMessage(); }, 2000);
}

function clearErrorMessage() {
    const messageContainer = document.getElementById('messages');
    const lastMessage = messageContainer.lastChild;
    if (lastMessage && lastMessage.textContent.includes('er is iets misgegaan')) {
        messageContainer.removeChild(lastMessage);
    }
}

/* Init */
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

window.onload = async () => {
    await startThread();
    addOpeningMessage();
    addPlaceholders();
    checkInput();
    document.getElementById('user-input').placeholder = "Vertel me wat je zoekt!";
    const applyFiltersButton = document.querySelector('button[onclick="applyFiltersAndSend()"]');
    if (applyFiltersButton) applyFiltersButton.onclick = applyFiltersAndSend;
    resetFilters();
    linkedPPNs.clear();
    closeFilterPanel();
    closeResultPanel();
    if (!history.state) history.replaceState({ panel: 'chat' }, '', location.pathname);
};
