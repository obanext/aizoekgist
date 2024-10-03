let currentNotificationId = null;

function addNotification(id) {
    const notificationsContainer = document.getElementById('notifications');
    const notificationElement = document.createElement('div');
    notificationElement.textContent = `Nieuw verzoek: ${id}`;
    notificationElement.onclick = () => {
        notifyUser(id);
    };
    notificationsContainer.appendChild(notificationElement);
}

async function notifyUser(humanAgentId) {
    try {
        await fetch('/send_message_to_user', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: humanAgentId, message: 'Hier is een OBA mens!' })
        });
        displayHumanMessage('Hier is een OBA mens!');
    } catch (error) {
        console.error('Error sending message to user:', error);
    }
}

async function sendHumanMessage() {
    const humanInput = document.getElementById('human-input').value.trim();
    if (humanInput === "") {
        return;
    }
    try {
        await fetch('/send_message_to_user', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: currentNotificationId, message: humanInput })
        });
        document.getElementById('human-input').value = '';
    } catch (error) {
        console.error('Error sending message:', error);
    }
}

function displayHumanMessage(message) {
    const messageContainer = document.getElementById('messages');
    const messageElement = document.createElement('div');
    messageElement.classList.add('human-message');
    messageElement.textContent = message;
    messageContainer.appendChild(messageElement);
}

async function fetchNotifications() {
    try {
        const response = await fetch('/get_notifications');
        if (response.ok) {
            const notifications = await response.json();
            notifications.forEach(id => {
                addNotification(id);
            });
        }
    } catch (error) {
        console.error('Error fetching notifications:', error);
    }
}

setInterval(fetchNotifications, 5000);
