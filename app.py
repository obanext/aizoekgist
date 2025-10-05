from flask import Flask, request, jsonify, render_template, g
import os
import logging
import time
import requests

from services import conversations_client  # create_conversation, ask_with_tools
from services.oba_helpers import make_envelope  # normalize_message zit daarin verwerkt

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]

# Alleen nog nodig voor proxies
OBA_API_KEY = os.environ["OBA_API_KEY"]

# === Logging ===
logger = logging.getLogger("oba_app")
logger.setLevel(getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO))
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(h)
logger.propagate = False

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
    return jsonify({"thread_id": conversation_id})

@app.route("/send_message", methods=["POST"])
def send_message():
    data = request.json or {}
    cid = data.get("thread_id")
    user_text = data.get("user_input", "")

    out = conversations_client.ask_with_tools(cid, user_text)

    # Altijd JSON naar frontend
    if isinstance(out, dict):
        return jsonify(out)
    return jsonify(make_envelope("text", message=str(out), thread_id=cid))

@app.route("/apply_filters", methods=["POST"])
def apply_filters():
    data = request.json or {}
    cid = data.get("thread_id")
    filters = (data.get("filter_values") or "").strip()

    # Hint voor model dat dit filterkeuzes zijn
    prompt = f"[FILTER] {filters}"
    out = conversations_client.ask_with_tools(cid, prompt)

    if isinstance(out, dict):
        return jsonify(out)
    return jsonify(make_envelope("text", message=str(out), thread_id=cid))

# === Proxies blijven handig voor detailpagina's ===
@app.route('/proxy/resolver')
def proxy_resolver():
    ppn = request.args.get('ppn')
    url = f'https://zoeken.oba.nl/api/v1/resolver/ppn/?id={ppn}&authorization={OBA_API_KEY}'
    r = requests.get(url, timeout=15)
    return r.content, r.status_code, r.headers.items()

# api.py
@app.route('/proxy/details')
def proxy_details():
    item_id = request.args.get('item_id')
    if not item_id:
        return "Missing item_id", 400

    url = f'https://zoeken.oba.nl/api/v1/details/?id=|oba-catalogus|{item_id}&authorization={OBA_API_KEY}&output=json'
    print("url of book detail"+url)
    r = requests.get(url, timeout=15)
    return r.content, r.status_code, r.headers.items()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
