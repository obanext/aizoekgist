import os
import json
import requests
from datetime import datetime, timezone

LOG_WEBHOOK_URL = os.environ.get("LOG_WEBHOOK_URL")
LOG_WEBHOOK_TOKEN = os.environ.get("LOG_WEBHOOK_TOKEN")

def handler(request, response):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return response.status(400).json({"error": "invalid json"})

    # Check token
    if data.get("token") != LOG_WEBHOOK_TOKEN:
        return response.status(401).json({"error": "unauthorized"})

    # Voeg timestamp toe als die ontbreekt
    if "timestamp" not in data:
        data["timestamp"] = datetime.now(timezone.utc).isoformat()

    # Stuur asynchroon door naar Google Apps Script
    try:
        requests.post(LOG_WEBHOOK_URL, json=data, timeout=1)
    except Exception:
        pass

    # Geef direct OK terug aan Nexi
    return response.status(200).json({"status": "queued"})
