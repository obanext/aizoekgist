let thread_id = null;
let timeoutHandle = null;
let previousResults = [];
let linkedPPNs = new Set();

function checkInput() {
    const userInput = document.getElementById('user-input').value.trim();
    const sendButton = document.getElementById('send-button');
    const applyFiltersButton = document.getElementById('apply-filters-button');
    const checkboxes = document.querySelectorAll('#filters input[type="checkbox"]');
    let anyChecked = Array.from(checkboxes).some(checkbox => checkbox.checked);

    if (userInput === "") {
        sendButton.disabled = true;
        sendButton.style.backgroundColor = "#ccc";
        sendButton.style.cursor = "not-allowed";
    } else {
        sendButton.disabled = false;
        sendButton.style.backgroundColor = "#6d5ab0";
        sendButton.style.cursor = "pointer";
    }

    if (!anyChecked) {
        applyFiltersButton.disabled = true;
        applyFiltersButton.style.backgroundColor = "#ccc";
        applyFiltersButton.style.cursor = "not-allowed";
    } else {
        applyFiltersButton.disabled = false;
        applyFiltersButton.style.backgroundColor = "#6d5ab0";
        applyFiltersButton.style.cursor = "pointer";
    }
}

async function startThread() {
    const response = await fetch('/start_thread', { method: 'POST' });
    const data = await response.json();
    thread_id = data.thread_id;
}

async function sendMessage() {
    const userInput = document.getElementById('user-input').value.trim();

    if (userInput === "") {
        return;
    }

    if (userInput.toLowerCase().includes('paprika')) {
        const response = await fetch('/request_handover', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: userInput, thread_id: thread_id })
        });

        const data = await response.json();

        if (data.handover === 'success') {
            displayAssistantMessage("Een menselijke agent zal het gesprek overnemen.");
        } else {
            displayAssistantMessage("Er is een fout opgetreden bij het verzoek om een menselijke agent.");
        }

        return;
    }

    displayUserMessage(userInput);
    showLoader();
    
    const sendButton = document.getElementById('send-button');
    document.getElementById('user-input').value = '';
    sendButton.disabled = true;
    sendButton.style.backgroundColor = "#ccc";
    sendButton.style.cursor = "not-allowed";

    document.getElementById('search-results').style.display = 'grid';
    document.getElementById('detail-container').style.display = 'none';
    document.getElementById('breadcrumbs').innerHTML = '';

    timeoutHandle = setTimeout(() => {
        showErrorMessage();
    }, 30000);

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
            const errorData = await response.json();
            showErrorMessage();
            return;
        }
        const data = await response.json();
        hideLoader();
        clearTimeout(timeoutHandle);

        if (!data.response.results) {
            displayAssistantMessage(data.response);
        }

        if (data.thread_id) {
            thread_id = data.thread_id;
        }

        if (data.response.results) {
            previousResults = data.response.results;
            displaySearchResults(data.response.results);
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
        if (!response.ok) {
            const errorData = await response.json();
            console.error('Error:', errorData.error);
            return;
        }
        const data = await response.json();
        displayAssistantMessage(data.response);
        scrollToBottom();
    } catch (error) {
        console.error('Unexpected error:', error);
    }
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
    searchResultsContainer.innerHTML = '';
    results.forEach(result => {
        const resultElement = document.createElement('div');
        resultElement.classList.add('search-result');
        resultElement.innerHTML = `
            <div onclick="fetchAndShowDetailPage('${result.ppn}')">
                <img src="https://cover.biblion.nl/coverlist.dll/?doctype=morebutton&bibliotheek=oba&style=0&ppn=${result.ppn}&isbn=&lid=&aut=&ti=&size=150" alt="Cover for PPN ${result.ppn}">
                <p>${result.titel}</p>
            </div>
        `;
        searchResultsContainer.appendChild(resultElement);
    });
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
                            <button onclick="window.open('https://zoeken.oba.nl/resolve.ashx?index=ppn&identifiers=${ppn}', '_blank')">Meer informatie op OBA.nl</button>
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
            const errorText = await detailResponse.text();
            throw new Error(`Unexpected response content type: ${errorText}`);
        }
    } catch (error) {
        console.error('Error fetching detail page:', error);
        displayAssistantMessage('😿 Er is iets misgegaan bij het ophalen van de detailpagina.');
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

    if (filterString === "") {
        return;
    }

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
            const errorData = await response.json();
            console.error('Error:', errorData.error);
            hideLoader();
            return;
        }

        const data = await response.json();
        hideLoader();

        if (data.results) {
            previousResults = data.results;
            displaySearchResults(data.results);
            await sendStatusKlaar();
        }

        if (data.thread_id) {
            thread_id = data.thread_id;
        }
        
        resetFilters();
    } catch (error) {
        console.error('Unexpected error:', error);
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
        console.error('Error tijdens het verzenden van het help-bericht:', error);
        hideLoader();
        displayAssistantMessage('😿 Er is iets misgegaan. Probeer opnieuw.');
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
    checkboxes.forEach(checkbox => {
        checkbox.checked = false;
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
    if (loaderElement) {
        loaderElement.remove();
    }

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
    const openingMessage = "Hoi! Ik ben Nexi, ik help je zoeken naar boeken en informatie in de OBA. Bijvoorbeeld: 'boeken die lijken op Wereldspionnen' of 'heb je informatie over zeezoogdieren?'"
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
    displayAssistantMessage('😿 er is iets misgegaan, we beginnen opnieuw!');
    hideLoader();
    clearTimeout(timeoutHandle);
    resetThread();

    setTimeout(() => {
        clearErrorMessage();
    }, 2000);
}

function clearErrorMessage() {
    const messageContainer = document.getElementById('messages');
    const lastMessage = messageContainer.lastChild;

    if (lastMessage && lastMessage.textContent.includes('er is iets misgegaan')) {
        messageContainer.removeChild(lastMessage);
    }
}

document.getElementById('user-input').addEventListener('input', function() {
    checkInput();
    if (this.value !== "") {
        this.placeholder = "";
    }
});
document.getElementById('user-input').addEventListener('keypress', function(event) {
    if (event.key === 'Enter') {
        sendMessage();
    }
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
    if (applyFiltersButton) {
        applyFiltersButton.onclick = applyFiltersAndSend;
    }

    resetFilters();
    linkedPPNs.clear();
};
