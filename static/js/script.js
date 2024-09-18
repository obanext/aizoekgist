let GIST_ID;
let GITHUB_TOKEN;

async function fetchGist() {
    try {
        const response = await fetch(`https://api.github.com/gists/${GIST_ID}`, {
            headers: {
                'Authorization': `token ${GITHUB_TOKEN}`,
                'Accept': 'application/vnd.github.v3+json'
            }
        });
        const data = await response.json();
        return JSON.parse(data.files['logs.json'].content || '[]');
    } catch (error) {
        console.error('Error fetching Gist:', error);
        return [];
    }
}

async function updateGist(newLogs) {
    try {
        const existingLogs = await fetchGist();
        const updatedLogs = existingLogs.concat(newLogs);

        await fetch(`https://api.github.com/gists/${GIST_ID}`, {
            method: 'PATCH',
            headers: {
                'Authorization': `token ${GITHUB_TOKEN}`,
                'Accept': 'application/vnd.github.v3+json',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                files: {
                    'logs.json': {
                        content: JSON.stringify(updatedLogs, null, 2)
                    }
                }
            })
        })
        .then(response => response.json())
        .then(data => console.log('Gist bijgewerkt:', data))
        .catch(error => console.error('Error:', error));
    } catch (error) {
        console.error('Error updating Gist:', error);
    }
}

async function logMessages(userMessage, assistantMessage) {
    const newLog = {
        timestamp: new Date().toISOString(),
        user: userMessage,
        assistant: assistantMessage
    };
    logs.push(newLog);

    await updateGist([newLog]);
}
