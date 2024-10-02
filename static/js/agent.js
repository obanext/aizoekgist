async function checkForHandovers() {
    const response = await fetch('/handover_list');
    const data = await response.json();
    
    const handoverThreads = data.handover_threads;
    const handoverNotification = document.getElementById('handover-notification');
    const handoverList = document.getElementById('handover-list');

    if (handoverThreads.length > 0) {
        handoverNotification.innerText = 
            `Er zijn ${handoverThreads.length} gesprekken die menselijke interventie nodig hebben.`;
        handoverList.innerHTML = handoverThreads.map(thread => 
            `<p onclick="fetchThreadMessages('${thread}')">Thread ID: ${thread}</p>`).join('');
    } else {
        handoverNotification.innerText = 'Geen openstaande handover-verzoeken.';
        handoverList.innerHTML = '';
    }
}

async function fetchThreadMessages(thread_id) {
    const response = await fetch(`/get_thread_messages/${thread_id}`);
    const data = await response.json();

    if (data.error) {
        console.error('Error fetching thread messages:', data.error);
        return;
    }

 
    const messageContainer = document.getElementById('message-container');
    messageContainer.innerHTML = data.messages.map(message => 
        `<p><strong>${message.role}:</strong> ${message.content}</p>`).join('');
}

// Dit blijft hetzelfde, maar met een interval om de handovers op te halen
setInterval(checkForHandovers, 5000);

