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
            `<p class="clickable-thread" data-thread-id="${thread}">Thread ID: ${thread}</p>`
        ).join('');

        document.querySelectorAll('.clickable-thread').forEach(item => {
            item.addEventListener('click', function() {
                const threadId = this.getAttribute('data-thread-id');
                fetchThreadMessages(threadId);
            });
        });
    } else {
        handoverNotification.innerText = 'Geen openstaande handover-verzoeken.';
        handoverList.innerHTML = '';
    }
}

let currentThreadId = null;  // Houd bij welk thread-id momenteel actief is voor de agent

async function fetchThreadMessages(thread_id) {
    currentThreadId = thread_id;

    try {
        const response = await fetch(`/get_thread_messages/${thread_id}`);
        const data = await response.json();

        if (data.error) {
            console.error('Error fetching thread messages:', data.error);
            return;
        }

        const messageContainer = document.getElementById('message-container');
        messageContainer.innerHTML = data.messages.map(message => 
            `<p><strong>${message.role}:</strong> ${message.content}</p>`
        ).join('');

        // Verstuur 'OBA mens hier!' zodra de agent op de thread klikt
        await fetch(`/agent_join_thread/${thread_id}`, { method: 'POST' });

    } catch (error) {
        console.error('Error fetching thread messages:', error);
    }
}

async function sendAgentMessage() {
    const agentInput = document.getElementById('agent-input').value.trim();

    if (!agentInput || !currentThreadId) {
        return;  // Stop als er geen bericht is of geen actief thread-id
    }

    // Verstuur het agent-bericht naar de server
    const response = await fetch('/send_agent_message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            thread_id: currentThreadId,
            message: agentInput
        })
    });

    const data = await response.json();

    if (data.status === 'success') {
        // Voeg het bericht toe aan de chatinterface
        const messageContainer = document.getElementById('message-container');
        messageContainer.innerHTML += `<p><strong>Agent:</strong> ${agentInput}</p>`;
        document.getElementById('agent-input').value = '';  // Clear inputveld
    } else {
        console.error('Error sending agent message:', data.error);
    }
}

function checkAgentInput() {
    const agentInput = document.getElementById('agent-input').value.trim();
    const sendButton = document.getElementById('send-agent-message');
    sendButton.disabled = !agentInput;  // Schakel de knop in of uit afhankelijk van input
}

setInterval(checkForHandovers, 5000);  // Blijf de lijst met openstaande handovers controleren
