let thread_id = null;

async function sendMessageToUser() {
    const agentMessage = document.getElementById('agent-message').value.trim();
    if (agentMessage === "") return;

    displayAgentMessage(agentMessage);

    try {
        const response = await fetch('/human_send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                thread_id: thread_id,
                message: agentMessage
            })
        });

        const data = await response.json();
        displayUserMessage(data.response);
    } catch (error) {
    }

    document.getElementById('agent-message').value = '';
}

function displayUserMessage(message) {
    const messageContainer = document.getElementById('agent-messages');
    const messageElement = document.createElement('div');
    messageElement.classList.add('user-message');
    messageElement.textContent = message;
    messageContainer.appendChild(messageElement);
    scrollToBottom();
}

function displayAgentMessage(message) {
    const messageContainer = document.getElementById('agent-messages');
    const messageElement = document.createElement('div');
    messageElement.classList.add('agent-message');
    messageElement.textContent = message;
    messageContainer.appendChild(messageElement);
    scrollToBottom();
}

function scrollToBottom() {
    const messageContainer = document.getElementById('agent-messages');
    messageContainer.scrollTop = messageContainer.scrollHeight;
}

window.onload = async () => {
    // Load the thread id when the agent interface is loaded
    const urlParams = new URLSearchParams(window.location.search);
    thread_id = urlParams.get('thread_id');
};
