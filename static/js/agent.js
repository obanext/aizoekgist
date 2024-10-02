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
            `<p class="clickable-thread" data-thread-id="${thread}">Thread ID: ${thread}</p>`).join('');

      
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

setInterval(checkForHandovers, 5000);

