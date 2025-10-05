from flask import Flask, request, jsonify, render_template, g
import os
import logging
import time
import requests
import threading
from datetime import datetime, timezone
import json

from services import conversations_client  # create_conversation, ask_with_tools
from services.oba_helpers import make_envelope  # normalize_message zit daarin verwerkt

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]

# Alleen nog nodig voor proxies
OBA_API_KEY = os.environ["OBA_API_KEY"]

# === Google Sheet logging configuratie ===
LOG_WEBHOOK_URL = os.environ.get("LOG_WEBHOOK_URL")
LOG_WEBHOOK_TOKEN = os.environ.get("LOG_WEBHOOK_TOKEN")
LOG_ENABLE = os.environ.get("LOG_ENABLE", "true").lower() in ("1", "true", "yes")


# === Logging setup ===
logger = logging.getLogger("oba_app")
logger.setLevel(getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO))
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(h)
logger.propagate = False


# === Helpers ===
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_text(text: str, max_len: int = 4000) -> str:
    """Maakt tekst veilig en knipt af bij te lange waarden."""
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False)
        except Exception:
            text = str(text)
    if len(text) > max_len:
        return text[:max_len] + f"… (trimmed {len(text) - max_len} chars)"
    return text

def _post_log_row(row: dict):
    """Stuurt log via interne Vercel proxy (supersnel)."""
    if not LOG_ENABLE or not LOG_WEBHOOK_TOKEN:
        return
    try:
        payload = {
            "token": LOG_WEBHOOK_TOKEN,
            "cid": row.get("cid") or "",
            "type": row.get("type") or "",
            "message": _sanitize_text(row.get("message") or ""),
            "meta": row.get("meta") or {},
        }
        # Proxy is binnen hetzelfde domein – zeer snel
        requests.post("https://nexitext.vercel.app/api/log_proxy",
                      json=payload, timeout=1)
    except Exception:
        pass


# === Timing logs ===
@app.before_request
def _start_timer():
    g.start_time = time.time()


@app.after_request
def _log_response(resp):
    dur = (time.time() - g.start_time) if hasattr(g, 'start_time') else -1
    logger.info(f"http {request.method} {request.path} status={resp.status_code} dur_ms={int(dur*1000)}")
    return resp


@app.errorhandler(Exception)
def _handle_error(e):
    logger.exception("unhandled_error")
    return jsonify({"error": "internal server error"}), 500


# === Routes ===
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/start_thread", methods=["POST"])
def start_thread():
    conversation_id = conversations_client.create_conversation()
    _post_log_row({
        "cid": conversation_id,
        "type": "THREAD_START",
        "message": "Nieuwe conversatie gestart",
        "meta": {"route": "/start_thread"}
    })
    return jsonify({"thread_id": conversation_id})


@app.route("/send_message", methods=["POST"])
def send_message():
    data = request.json or {}
    cid = data.get("thread_id")
    user_text = data.get("user_input", "")

    # Log de vraag
    _post_log_row({"cid": cid, "type": "Q", "message": user_text, "meta": {"route": "/send_message"}})

    out = conversations_client.ask_with_tools(cid, user_text)

    # Log het antwoord
    if isinstance(out, dict):
        resp = out.get("response", {}) or {}
        msg = resp.get("message") or str(out)
        _post_log_row({"cid": cid, "type": "A", "message": msg, "meta": {"route": "/send_message"}})
        return jsonify(out)

    _post_log_row({"cid": cid, "type": "A", "message": str(out), "meta": {"route": "/send_message"}})
    return jsonify(make_envelope("text", message=str(out), thread_id=cid))


@app.route("/apply_filters", methods=["POST"])
def apply_filters():
    data = request.json or {}
    cid = data.get("thread_id")
    filters = (data.get("filter_values") or "").strip()

    _post_log_row({"cid": cid, "type": "Q_FILTER", "message": filters, "meta": {"route": "/apply_filters"}})

    prompt = f"[FILTER] {filters}"
    out = conversations_client.ask_with_tools(cid, prompt)

    if isinstance(out, dict):
        resp = out.get("response", {}) or {}
        msg = resp.get("message") or str(out)
        _post_log_row({"cid": cid, "type": "A", "message": msg, "meta": {"route": "/apply_filters"}})
        return jsonify(out)

    _post_log_row({"cid": cid, "type": "A", "message": str(out), "meta": {"route": "/apply_filters"}})
    return jsonify(make_envelope("text", message=str(out), thread_id=cid))


# === Proxies ===
@app.route('/proxy/resolver')
def proxy_resolver():
    ppn = request.args.get('ppn')
    url = f'https://zoeken.oba.nl/api/v1/resolver/ppn/?id={ppn}&authorization={OBA_API_KEY}'
    r = requests.get(url, timeout=15)
    return r.content, r.status_code, r.headers.items()


@app.route('/proxy/details')
def proxy_details():
    item_id = request.args.get('item_id')
    if not item_id:
        return "Missing item_id", 400

    url = f'https://zoeken.oba.nl/api/v1/details/?id=|oba-catalogus|{item_id}&authorization={OBA_API_KEY}&output=json'
    print("url of book detail" + url)
    r = requests.get(url, timeout=15)
    return r.content, r.status_code, r.headers.items()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
