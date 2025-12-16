// /static/js/script.js

let thread_id = null;
let timeoutHandle = null;
let previousResults = [];
let linkedPPNs = new Set();

/* ===== Mobiele helpers ===== */
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
    if (useHistoryBack && history.state?.panel === 'filters') history.back();
}

function closeResultPanel(useHistoryBack = false) {
    const panel = document.getElementById('result-section');
    panel.classList.remove('open');
    if (!document.getElementById('filter-section').classList.contains('open')) {
        document.body.classList.remove('panel-open');
    }
    updateActionButtons();
    if (useHistoryBack && history.state?.panel === 'results') history.back();
}

function closeAnyPanel() {
    closeFilterPanel();
    closeResultPanel();
}

/* ===== Input & buttons ===== */
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
    if (!url) return;

    const res = await fetch(url);
    const html = await res.text();
    document.getElementById("filter-options").innerHTML = html;

    document.querySelectorAll('#filter-options input').forEach(el => {
        el.addEventListener('change', checkInput);
    });
    checkInput();
}

function resetFilters() {
    document.querySelectorAll('#filter-options input[type="radio"]').forEach(r => r.checked = false);
    checkInput();
}

/* ===== Chat ===== */
async function startThread() {
    const r = await fetch('/start_thread', { method: 'POST' });
    const d = await r.json();
    thread_id = d.thread_id;
}

async function sendMessage() {
    const input = document.getElementById('user-input').value.trim();
    if (!input) return;

    displayUserMessage(input);
    showLoader();
    document.getElementById('user-input').value = '';
    checkInput();

    try {
        const r = await fetch('/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ thread_id, user_input: input })
        });
        const data = await r.json();
        hideLoader();
        handleResponse(data.response);
    } catch {
        showErrorMessage();
    }
}

function handleResponse(resp) {
    if (!resp) return;

    if (resp.type === 'collection') {
        previousResults = resp.results || [];
        displaySearchResults(previousResults);
        if (resp.message) displayAssistantMessage(resp.message);
        loadFilterTemplate("collection");
    } else if (resp.type === 'agenda') {
        previousResults = resp.results || [];
        displayAgendaResults(previousResults);
        if (resp.message) displayAssistantMessage(resp.message);
        loadFilterTemplate("agenda");
    } else if (resp.type === 'faq') {
        if (resp.message) displayAssistantMessage(resp.message);
        previousResults = [];
    } else {
        displayAssistantMessage(resp.message || 'Onbekend antwoord.');
        previousResults = [];
    }

    resetFilters();
}

/* ===== Filters toepassen ===== */
async function applyFiltersAndSend() {
    let filterString = "";

    const agendaLocation = document.getElementById("agenda-location");
    if (agendaLocation) {
        const sel = [];
        if (agendaLocation.value) sel.push(`Locatie: ${agendaLocation.value}`);
        if (document.getElementById("agenda-age")?.value) sel.push(`Leeftijd: ${document.getElementById("agenda-age").value}`);
        if (document.getElementById("agenda-date")?.value) sel.push(`Wanneer: ${document.getElementById("agenda-date").value}`);
        if (document.getElementById("agenda-type")?.value) sel.push(`Type: ${document.getElementById("agenda-type").value}`);
        filterString = sel.join("||");
    } else {
        const sel = [];
        const fic  = document.querySelector('input[name="fictie"]:checked');
        const nonf = document.querySelector('input[name="nonfictie"]:checked');
        const lang = document.querySelector('input[name="language"]:checked');

        if (fic)  sel.push(`Indeling: ${fic.value}`);
        if (nonf) sel.push(`Indeling: ${nonf.value}`);
        if (lang) sel.push(`Taal: ${lang.value}`);

        filterString = sel.join("||");
    }

    if (!filterString) return;

    displayUserMessage(`Filters toegepast: ${filterString}`);
    showLoader();

    try {
        const r = await fetch('/apply_filters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ thread_id, filter_values: filterString })
        });
        const data = await r.json();
        hideLoader();
        handleResponse(data.response);
    } catch {
        showErrorMessage();
    }
}

/* ===== UI helpers ===== */
function displayUserMessage(msg) {
    const el = document.createElement('div');
    el.className = 'user-message';
    el.textContent = msg;
    document.getElementById('messages').appendChild(el);
}

function displayAssistantMessage(msg) {
    const el = document.createElement('div');
    el.className = 'assistant-message';
    el.innerHTML = msg;
    document.getElementById('messages').appendChild(el);
}

function showLoader() {
    const el = document.createElement('div');
    el.id = 'loader';
    el.className = 'assistant-message';
    el.textContent = '...';
    document.getElementById('messages').appendChild(el);
}

function hideLoader() {
    document.getElementById('loader')?.remove();
}

function showErrorMessage() {
    hideLoader();
    displayAssistantMessage('Er is iets misgegaan.');
}

/* ===== Init ===== */
window.onload = async () => {
    await startThread();
    checkInput();
    document.getElementById('send-button').onclick = sendMessage;
    document.getElementById('apply-filters-button').onclick = applyFiltersAndSend;
};
