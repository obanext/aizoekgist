async function checkForHandovers() {
    const response = await fetch('/handover_list');
    const data = await response.json();

  
    const handoverThreads = data.handover_threads;
    const handoverNotification = document.getElementById('handover-notification');
    const handoverList = document.getElementById('handover-list');


    if (handoverThreads.length > 0) {
        handoverNotification.innerText = 
            `Er zijn ${handoverThreads.length} gesprekken die menselijke interventie nodig hebben.`;
        handoverList.innerHTML = handoverThreads.map(thread => `<p>Thread ID: ${thread}</p>`).join('');
    } else {
        handoverNotification.innerText = 'Geen openstaande handover-verzoeken.';
        handoverList.innerHTML = '';
    }
}


setInterval(checkForHandovers, 5000);
