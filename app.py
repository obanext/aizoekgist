from flask import Flask, request, jsonify, render_template, g
import os
import logging
import time
import requests
import json
from datetime import datetime, timezone

from services import conversations_client
from services.oba_helpers import make_envelope

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
OBA_API_KEY = os.environ["OBA_API_KEY"]

LOG_WEBHOOK_URL = os.environ.get("LOG_WEBHOOK_URL")
LOG_WEBHOOK_TOKEN = os.environ.get("LOG_WEBHOOK_TOKEN")
LOG_ENABLE = os.environ.get("LOG_ENABLE", "true").lower() in ("1", "true", "yes")

logger = logging.getLogger("oba_app")
logger.setLevel(getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO))
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(h)
logger.propagate = False

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _sanitize_text(text: str, max_len: int = 4000) -> str:
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False)
        except Exception:
            text = str(text)
    if len(text) > max_len:
        return text[:max_len] + f"… (trimmed {len(text) - max_len} chars)"
    return text

def _post_log_row(row: dict):
    if not LOG_ENABLE or not LOG_WEBHOOK_URL or not LOG_WEBHOOK_TOKEN:
        return
    try:
        payload = {
            "token": LOG_WEBHOOK_TOKEN,
            "timestamp": _utc_now_iso(),
            "cid": row.get("cid") or "",
            "type": row.get("type") or "",
            "message": _sanitize_text(row.get("message") or ""),
            "meta": row.get("meta") or {},
        }
        requests.post(LOG_WEBHOOK_URL, json=payload, timeout=3)
    except Exception:
        pass

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
    try:
        _post_log_row({
            "cid": request.json.get("thread_id") if request.is_json else "",
            "type": "ERROR",
            "message": f"{type(e).__name__}: {str(e)}",
            "meta": {"path": request.path, "method": request.method}
        })
    except Exception:
        pass
    return jsonify({"error": "internal server error"}), 500

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
    logger.info(f"[Q] (cid={cid}) {user_text}")
    _post_log_row({"cid": cid, "type": "Q", "message": user_text, "meta": {"route": "/send_message"}})
    out = conversations_client.ask_with_tools(cid, user_text)
    if isinstance(out, dict):
        resp = out.get("response", {}) or {}
        answer_msg = resp.get("message") or ""
        answer_type = resp.get("type") or "text"
        results_len = len(resp.get("results") or [])
    else:
        answer_msg = str(out)
        answer_type = "text"
        results_len = 0
    logger.info(f"[A] (cid={cid}) {answer_msg}")
    _post_log_row({"cid": cid, "type": "A", "message": answer_msg, "meta": {"route": "/send_message", "resp_type": answer_type, "results": results_len}})
    if isinstance(out, dict):
        return jsonify(out)
    return jsonify(make_envelope("text", message=str(out), thread_id=cid))

@app.route("/apply_filters", methods=["POST"])
def apply_filters():
    data = request.json or {}
    cid = data.get("thread_id")
    fv = data.get("filter_values")
    filters = fv.strip() if isinstance(fv, str) else (fv or "")
    logger.info(f"[Q_FILTER] (cid={cid}) {filters}")
    _post_log_row({"cid": cid, "type": "Q_FILTER", "message": filters, "meta": {"route": "/apply_filters"}})
    prompt = f"[FILTER] {filters}"
    out = conversations_client.ask_with_tools(cid, prompt)
    if isinstance(out, dict):
        resp = out.get("response", {}) or {}
        answer_msg = resp.get("message") or ""
        answer_type = resp.get("type") or "text"
        results_len = len(resp.get("results") or [])
    else:
        answer_msg = str(out)
        answer_type = "text"
        results_len = 0
    logger.info(f"[A] (cid={cid}) {answer_msg}")
    _post_log_row({"cid": cid, "type": "A", "message": answer_msg, "meta": {"route": "/apply_filters", "resp_type": answer_type, "results": results_len}})
    if isinstance(out, dict):
        return jsonify(out)
    return jsonify(make_envelope("text", message=str(out), thread_id=cid))

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
