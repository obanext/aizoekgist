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
    const hasOpen =
        document.getElementById('filter-section').classList.contains('open') ||
        document.getElementById('result-section').classList.contains('open');
    closeFilterPanel();
    closeResultPanel();
    if (hasOpen && history.state && history.state.panel) {
        history.back();
    }
}

/* ===== Input & knoppen ===== */
function checkInput() {
    const userInput = document.getElementById('user-input').value.trim();
    const sendButton = document.getElementById('send-button');
    const applyFiltersButton = document.getElementById('apply-filters-button');

    sendButton.disabled = userInput === "";

    let anySelected = false;

    const agendaLocation = document.getElementById("agenda-location");
    if (agendaLocation) {
        const loc  = agendaLocation.value;
        const age  = document.getElementById("agenda-age")?.value;
        const date = document.getElementById("agenda-date")?.value;
        const type = document.getElementById("agenda-type")?.value;
        anySelected = !!(loc || age || date || type);
    } else {
        const fic  = document.querySelector('input[name="fictie"]:checked');
        const nonf = document.querySelector('input[name="nonfictie"]:checked');
        const lang = document.querySelector('input[name="language"]:checked');
        anySelected = !!(fic || nonf || lang);
    }

    applyFiltersButton.disabled = !anySelected;
}

/* ===== Filters ===== */
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

    document.querySelectorAll('#filter-options input').forEach(el => {
        el.addEventListener('change', checkInput);
    });
    checkInput();
}

function resetFilters() {
    document.querySelectorAll('#filter-options input[type="radio"]').forEach(r => {
        r.checked = false;
    });
    checkInput();
}

/* ===== Chat ===== */
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

    timeoutHandle = setTimeout(() => { showErrorMessage(); }, 30000);

    try {
        const response = await fetch('/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ thread_id, user_input: userInput })
        });

        if (!response.ok) {
            showErrorMessage();
            return;
        }

        const data = await response.json();
        hideLoader();
        clearTimeout(timeoutHandle);

        handleResponse(data.response);
    } catch {
        showErrorMessage();
    }
}

function handleResponse(resp) {
    if (!resp) return;

    switch (resp.type) {
        case 'collection':
            previousResults = resp.results || [];
            displaySearchResults(previousResults);
            if (resp.message) displayAssistantMessage(resp.message);
            loadFilterTemplate("collection");
            break;

        case 'agenda':
            previousResults = resp.results || [];
            displayAgendaResults(previousResults);
            if (resp.message) displayAssistantMessage(resp.message);
            loadFilterTemplate("agenda");
            break;

        case 'faq':
            if (resp.message) displayAssistantMessage(resp.message);
            previousResults = [];
            document.getElementById("filter-options").innerHTML = "";
            break;

        default:
            displayAssistantMessage(resp.message || 'Ik heb je vraag niet begrepen.');
            previousResults = [];
            document.getElementById("filter-options").innerHTML = "";
    }

    resetFilters();
}

/* ===== Filters toepassen ===== */
async function applyFiltersAndSend() {
    let filterString = "";

    const agendaLocation = document.getElementById("agenda-location");
    if (agendaLocation) {
        const selected = [];
        if (agendaLocation.value) selected.push(`Locatie: ${agendaLocation.value}`);
        if (document.getElementById("agenda-age")?.value) selected.push(`Leeftijd: ${document.getElementById("agenda-age").value}`);
        if (document.getElementById("agenda-date")?.value) selected.push(`Wanneer: ${document.getElementById("agenda-date").value}`);
        if (document.getElementById("agenda-type")?.value) selected.push(`Type: ${document.getElementById("agenda-type").value}`);
        filterString = selected.join("||");
    } else {
        const selected = [];
        const fic  = document.querySelector('input[name="fictie"]:checked');
        const nonf = document.querySelector('input[name="nonfictie"]:checked');
        const lang = document.querySelector('input[name="language"]:checked');

        if (fic)  selected.push(`Indeling: ${fic.value}`);
        if (nonf) selected.push(`Indeling: ${nonf.value}`);
        if (lang) selected.push(`Taal: ${lang.value}`);

        filterString = selected.join("||");
    }

    if (!filterString) return;

    displayUserMessage(`Filters toegepast: ${filterString}`);
    showLoader();

    try {
        const response = await fetch('/apply_filters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ thread_id, filter_values: filterString })
        });

        if (!response.ok) {
            hideLoader();
            return;
        }

        const data = await response.json();
        hideLoader();
        handleResponse(data.response);
    } catch {
        hideLoader();
    }
}

/* ===== UI helpers ===== */
function displayUserMessage(message) {
    const el = document.createElement('div');
    el.className = 'user-message';
    el.textContent = message;
    document.getElementById('messages').appendChild(el);
}

function displayAssistantMessage(message) {
    const el = document.createElement('div');
    el.className = 'assistant-message';
    el.innerHTML = message;
    document.getElementById('messages').appendChild(el);
}

function showLoader() {
    const el = document.createElement('div');
    el.id = 'loader';
    el.className = 'assistant-message loader';
    el.innerHTML = '<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span>';
    document.getElementById('messages').appendChild(el);
}

function hideLoader() {
    document.getElementById('loader')?.remove();
}

function showErrorMessage() {
    hideLoader();
    displayAssistantMessage('er is iets misgegaan, we beginnen opnieuw');
    resetThread();
}

function resetThread() {
    startThread();
    document.getElementById('messages').innerHTML = '';
    document.getElementById('search-results').innerHTML = '';
    document.getElementById('filter-options').innerHTML = '';
    addOpeningMessage();
}

/* ===== Init ===== */
document.getElementById('user-input').addEventListener('input', checkInput);
document.getElementById('user-input').addEventListener('keypress', e => {
    if (e.key === 'Enter') sendMessage();
});

window.onload = async () => {
    await startThread();
    addOpeningMessage();
    checkInput();
};
