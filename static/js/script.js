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
