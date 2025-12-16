// /static/js/script.js

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
    updateActionButtons();
    if (pushHistory) history.pushState({ panel: 'filters' }, '', '#filters');
}

function openResultPanel(pushHistory = true) {
    const panel = document.getElementById('result-section');
    const other = document.getElementById('filter-section');
    other.classList.remove('open');
    panel.classList.add('open');
    document.body.classList.add('panel-open');
    updateActionButtons();
    if (pushHistory) history.pushState({ panel: 'results' }, '', '#results');
}

function closeFilterPanel(useHistoryBack = false) {
    const panel = document.getElementById('filter-section');
    panel.classList.remove('open');
    if (!document.getElementById('result-section').classList.contains('open')) {
        document.body.classList.remove('panel-open');
    }
    updateActionButtons();
    if (useHistoryBack && history.state && history.state.panel === 'filters') {
        history.back();
    }
}

function closeResultPanel(useHistoryBack = false) {
    const panel = document.getElementById('result-section');
    panel.classList.remove('open');
    if (!document.getElementById('filter-section').classList.contains('open')) {
        document.body.classList.remove('panel-open');
    }
    updateActionButtons();
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
        updateActionButtons();
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

function decideAndLoadFilter(results) {
    if (!results || results.length === 0) {
        document.getElementById("filter-options").innerHTML = "";
        return;
    }
    const first = results[0];
    if (first.ppn) {
        loadFilterTemplate("collection");
    } else if (first.link) {
        loadFilterTemplate("agenda");
    } else {
        document.getElementById("filter-options").innerHTML = "";
    }
}

/* ===== Functionaliteit chat en zoekresultaten ===== */
function checkInput() {
  const userInput = document.getElementById('user-input').value.trim();
  const sendButton = document.getElementById('send-button');
  const applyFiltersButton = document.getElementById('apply-filters-button');

  if (sendButton) {
    sendButton.disabled = userInput === "";
    sendButton.style.backgroundColor = userInput === "" ? "#ccc" : "#6d5ab0";
    sendButton.style.cursor = userInput === "" ? "not-allowed" : "pointer";
  }

  if (!applyFiltersButton) return; // veiligheidsnet

  let anySelected = false;

  // Agenda: enable als één van de selects een waarde heeft
  const agendaLocation = document.getElementById("agenda-location");
  if (agendaLocation) {
    const loc  = (agendaLocation.value || "").trim();
    const age  = (document.getElementById("agenda-age")?.value || "").trim();
    const date = (document.getElementById("agenda-date")?.value || "").trim();
    const type = (document.getElementById("agenda-type")?.value || "").trim();
    anySelected = !!(loc || age || date || type);
  } else {
    // Collectie: enable als er minstens één checkbox aan staat
    const fic  = document.querySelector('input[name="fictie"]:checked');
    const nonf = document.querySelector('input[name="nonfictie"]:checked');
    const lang = document.querySelector('input[name="language"]:checked');
    anySelected = !!(fic || nonf || lang);
  }

  applyFiltersButton.disabled = !anySelected;
  applyFiltersButton.style.backgroundColor = anySelected ? "#6d5ab0" : "#ccc";
  applyFiltersButton.style.cursor = anySelected ? "pointer" : "not-allowed";
}

function updateActionButtons() {
    const resultsBtn = document.getElementById('open-results-btn');
    const filtersBtn = document.getElementById('open-filters-btn');
    const backBtn = document.getElementById('back-chat-btn');

    const hasResults = Array.isArray(previousResults) && previousResults.length > 0;
    const resultOpen = document.getElementById('result-section').classList.contains('open');
    const filterOpen = document.getElementById('filter-section').classList.contains('open');

    // standaard
    resultsBtn.style.display = 'none';
    filtersBtn.style.display = 'none';
    backBtn.style.display = 'none';

    if (filterOpen) {
        backBtn.style.display = 'inline-flex';
        backBtn.onclick = () => closeFilterPanel(true);
        resultsBtn.style.display = 'inline-flex';
        resultsBtn.disabled = !hasResults;
    } else if (resultOpen) {
        backBtn.style.display = 'inline-flex';
        backBtn.onclick = () => closeResultPanel(true);
        filtersBtn.style.display = 'inline-flex';
        filtersBtn.disabled = !hasResults;
    } else {
        resultsBtn.disabled = !hasResults;
        filtersBtn.disabled = !hasResults;
        resultsBtn.style.display = 'inline-flex';
        filtersBtn.style.display = 'inline-flex';
    }
}

async function loadFilterTemplate(type) {
    let url = "";
    if (type === "collection") url = "/static/html/filtercollectie.html";
    if (type === "agenda") url = "/static/html/filteragenda.html";

    if (!url) {
        document.getElementById("filter-options").innerHTML = "";
        return;
    }

    const res = await fetch(url);
    const html = await res.text();
    document.getElementById("filter-options").innerHTML = html;

    document.querySelectorAll('#filter-options input[type="radio"]').forEach(cb => {
        cb.addEventListener('change', checkInput);
    });
    document.querySelectorAll('#filter-options select').forEach(sel => {
        sel.addEventListener('change', checkInput);
    });
    checkInput();
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
        if (!response.ok) { showErrorMessage(); return; }

        const data = await response.json();
        console.log("[NEXITEXT][OUTPUT][SEND]", data);

        hideLoader();
        clearTimeout(timeoutHandle);

        const { response: resp, thread_id: newTid } = data;
        if (newTid) thread_id = newTid;

        switch (resp?.type) {
            case 'agenda':
            case 'collection': {
                previousResults = resp.results || [];
                if (resp.type === 'agenda') {
                    displayAgendaResults(previousResults);
                    if (resp.url) {
                        displayAssistantMessage(
                            `Bekijk alles op <a href="${resp.url}" target="_blank">OBA Agenda</a>`
                        );
                    }
                } else {
                    displaySearchResults(previousResults);
                }
                if (resp.message) displayAssistantMessage(resp.message);
                decideAndLoadFilter(previousResults);
                if (resp.type === 'agenda') await sendStatusKlaar();
                break;
            }
            case 'faq': {
                if (resp.message) displayAssistantMessage(resp.message);
                document.getElementById("filter-options").innerHTML = "";
                previousResults = [];
                break;
            }
            case 'text':
            default: {
                displayAssistantMessage(resp?.message || 'Ik heb je vraag niet helemaal begrepen.');
                document.getElementById("filter-options").innerHTML = "";
                previousResults = [];
                break;
            }
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
    updateActionButtons();
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
        const { response: resp } = data || {};
        if (resp?.message) {
            displayAssistantMessage(resp.message);
        } else if (resp && typeof resp === 'string') {
            displayAssistantMessage(resp);
        }
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
        const imgEl = resultElement.querySelector('img');
        loadCoverOrPlaceholder(imgEl.src, '/static/images/placeholder.png', (src) => {
            imgEl.src = src;
        });
    });

    updateResultsBadge(results.length);
    updateActionButtons();
}

function displayAgendaResults(results) {
    const searchResultsContainer = document.getElementById('search-results');
    searchResultsContainer.innerHTML = '';
    searchResultsContainer.classList.remove('book-grid');
    searchResultsContainer.classList.add('agenda-list');

    const maxItems = 10;
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
            window.open("https://oba.nl/nl/agenda/volledige-agenda", '_blank');
        };
        searchResultsContainer.appendChild(moreButton);
    }

    updateResultsBadge(results.length);
    updateActionButtons();
}

function displayFaqResults(results) {
    const searchResultsContainer = document.getElementById('search-results');
    searchResultsContainer.innerHTML = '';
    searchResultsContainer.classList.remove('book-grid', 'agenda-list');

    results.forEach(result => {
        const el = document.createElement('div');
        el.classList.add('faq-result');
        el.innerHTML = `<p>${result.antwoord}</p>`;
        searchResultsContainer.appendChild(el);
    });

    updateResultsBadge(results.length);
    updateActionButtons();
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
            const rec = detailJson?.record ?? {};

            const titles = Array.isArray(rec.titles) ? rec.titles : (rec.titles ? [rec.titles] : []);
            const covers = Array.isArray(rec.coverimages) ? rec.coverimages : (rec.coverimages ? [rec.coverimages] : []);
            const summaries = Array.isArray(rec.summaries) ? rec.summaries : [];
            const descriptions = Array.isArray(rec.description) ? rec.description : (rec.description ? [rec.description] : []);

            const title = titles[0] || 'Titel niet beschikbaar';
            const summary = summaries[0] || descriptions[0] || 'Samenvatting niet beschikbaar';
            const coverImage = covers[0] || '';

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
            const imgEl = detailContainer.querySelector('.detail-cover');
            loadCoverOrPlaceholder(imgEl.src, '/static/images/placeholder.png', (src) => {
                imgEl.src = src;
            });

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

function loadCoverOrPlaceholder(url, placeholderUrl, cb) {
  const img = new Image();
  img.onload = function () {
    if (img.naturalWidth < 2 || img.naturalHeight < 2) {
      cb(placeholderUrl);
    } else {
      cb(url);
    }
  };
  img.onerror = function () {
    cb(placeholderUrl);
  };
  img.src = url;
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
    let filterString = "";

    const agendaLocation = document.getElementById("agenda-location");
    if (agendaLocation) {
        const location = agendaLocation.value;
        const age = document.getElementById("agenda-age")?.value || "";
        const date = document.getElementById("agenda-date")?.value || "";
        const type = document.getElementById("agenda-type")?.value || "";

        const selected = [];
        if (location) selected.push(`Locatie: ${location}`);
        if (age) selected.push(`Leeftijd: ${age}`);
        if (date) selected.push(`Wanneer: ${date}`);
        if (type) selected.push(`Type: ${type}`);
        filterString = selected.join("||");
    } else {
        const fic  = document.querySelector('input[name="fictie"]:checked');
        const nonf = document.querySelector('input[name="nonfictie"]:checked');
        const lang = document.querySelector('input[name="language"]:checked');

        const selected = [];
        if (fic)  selected.push(`Indeling: ${fic.value}`);
        if (nonf) selected.push(`Indeling: ${nonf.value}`);
        if (lang) selected.push(`Taal: ${lang.value}`);
        filterString = selected.join("||");
    }

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

        if (!response.ok) { hideLoader(); return; }

        const data = await response.json();
        console.log("[NEXITEXT][OUTPUT][FILTER]", data);

        hideLoader();

        const { response: resp, thread_id: newTid } = data;
        if (newTid) thread_id = newTid;

        if (resp && resp.message && resp.type !== 'faq') {
            displayAssistantMessage(resp.message);
        }

        switch (resp?.type) {
            case 'agenda':
            case 'collection': {
                previousResults = resp.results || [];
                if (resp.type === 'agenda') {
                    displayAgendaResults(previousResults);
                } else {
                    displaySearchResults(previousResults);
                }
                decideAndLoadFilter(previousResults);
                break;
            }
            case 'faq': {
                const faqResults = resp.results || [];
                if (faqResults.length > 0) {
                    displayAssistantMessage(faqResults[0].antwoord);
                } else {
                    displayAssistantMessage("Ik heb daar geen antwoord op kunnen vinden.");
                }
                document.getElementById("filter-options").innerHTML = "";
                previousResults = [];
                break;
            }
            case 'text':
            default: {
                displayAssistantMessage(resp?.message || 'Onbekende filterrespons.');
                document.getElementById("filter-options").innerHTML = "";
                previousResults = [];
                break;
            }
        }

        resetFilters();

        if (window.innerWidth <= 768) {
            document.getElementById('filter-section').classList.remove('open');
            document.getElementById('result-section').classList.remove('open');
            document.body.classList.remove('panel-open');
            history.replaceState({ panel: 'chat' }, '', location.pathname);
            updateActionButtons();
        }

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
    updateActionButtons();
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

async function startNexiVoice(){
    window.location.assign("https://nexivoice.vercel.app/");
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
        const { response: resp } = data || {};
        if (resp?.message) {
            displayAssistantMessage(resp.message);
        } else if (resp && typeof resp === 'string') {
            displayAssistantMessage(resp);
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
    document.querySelectorAll('#filter-options input[type="radio"]').forEach(r => {
        r.checked = false;
    });
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
    const openingMessage = "Hoi! Ik ben Nexi, ik ben een AI-zoekhulp. Je kan mij alles vragen over boeken en events in de OBA. Bijvoorbeeld: 'boeken over prehistorische planteneters' of 'Wat is er te doen in OBA Next Lab Kraaiennest'? Ik ben een experiment en kan foute antwoorden of gedrag vertonen.";
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
    updateActionButtons();
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
    updateActionButtons();
};
