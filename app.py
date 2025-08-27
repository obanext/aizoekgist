from flask import Flask, request, jsonify, render_template, g
import openai
import json
import requests
import os
import xml.etree.ElementTree as ET
from datetime import datetime
import logging
import time

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]

# === Config ===
openai.api_key = os.environ["OPENAI_API_KEY"]
TYPESENSE_API_KEY = os.environ["TYPESENSE_API_KEY"]
TYPESENSE_API_URL = os.environ["TYPESENSE_API_URL"]
OBA_API_KEY = os.environ["OBA_API_KEY"]

assistant_ids = {
    "router": os.environ["ASSISTANT_ID_1"],
    "search": os.environ["ASSISTANT_ID_2"],
    "compare": os.environ["ASSISTANT_ID_3"],
    "agenda": os.environ["ASSISTANT_ID_4"],
}

# === Collections
COLLECTION_BOOKS = os.environ["COLLECTION_BOOKS"]
COLLECTION_FAQ = os.environ["COLLECTION_FAQ"]
COLLECTION_EVENTS = os.environ["COLLECTION_EVENTS"]

# === Logging ===
logger = logging.getLogger("oba_app")
logger.setLevel(getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO))
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(h)
logger.propagate = False

active_agents = {}

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

# === Helpers ===
def make_envelope(resp_type, results=None, url=None, message=None, thread_id=None):
    return {
        "response": {
            "type": resp_type,
            "url": url,
            "message": normalize_message(message),
            "results": results or []
        },
        "thread_id": thread_id
    }

def error_envelope(msg, thread_id):
    return jsonify(make_envelope("text", [], None, msg, thread_id))

def extract_marker(text, marker):
    return text.split(marker, 1)[1].strip() if text and marker in text else None

def normalize_message(raw):
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed.get("Message")
            return raw
        except:
            return raw
    if isinstance(raw, dict):
        return raw.get("Message")
    return str(raw)

# === OpenAI main call: streaming (met juiste event-loop) ===
def call_assistant(agent_key, user_input, thread_id=None):
    try:
        if not thread_id:
            thread = openai.beta.threads.create()
            thread_id = thread.id
            logger.info(f"thread_new id={thread_id}")

        openai.beta.threads.messages.create(
            thread_id=thread_id, role="user", content=user_input
        )

        logger.info(f"assistant_call agent={agent_key} thread={thread_id} input_len={len(user_input)}")

        response_text = ""
        with openai.beta.threads.runs.stream(
            thread_id=thread_id,
            assistant_id=assistant_ids[agent_key]
        ) as stream:
            for ev in stream:
                etype = getattr(ev, "type", None)
                cls = ev.__class__.__name__

                # 1. Tekst via ThreadMessageDelta
                if cls == "ThreadMessageDelta":
                    for block in ev.data.delta.content:
                        if block.type == "text":
                            response_text += block.text.value

                # 2. Tekst via response.output_text.delta (fallback)
                elif etype == "response.output_text.delta":
                    response_text += ev.delta

            stream.until_done()

        logger.info(f"assistant_done agent={agent_key} thread={thread_id} output_len={len(response_text)}")
        return response_text, thread_id

    except Exception:
        logger.exception("openai_error")
        return "", thread_id

# === Typesense ===
def typesense_search(params, include_fields="short_title,ppn"):
    headers = {"Content-Type": "application/json", "X-TYPESENSE-API-KEY": TYPESENSE_API_KEY}
    body = {"searches": [{
        "q": params.get("q"),
        "query_by": params.get("query_by"),
        "collection": params.get("collection"),
        "prefix": "false",
        "vector_query": params.get("vector_query"),
        "include_fields": include_fields,
        "per_page": 15,
        "filter_by": params.get("filter_by")
    }]}
    logger.info(f"typesense_request collection={params.get('collection')} q_len={len(params.get('q',''))}")
    r = requests.post(TYPESENSE_API_URL, headers=headers, json=body, timeout=15)
    logger.info(f"typesense_response status={r.status_code}")
    if r.status_code != 200:
        logger.warning(f"typesense_error status={r.status_code} body={r.text[:200]}")
        return {"results": []}
    data = r.json()["results"][0]["hits"]
    if include_fields == "nativeid":
        logger.info(f"typesense_hits events count={len(data)}")
        return [h["document"].get("nativeid") for h in data if h.get("document")]
    logger.info(f"typesense_hits books count={len(data)}")
    return {"results": [{"ppn": h["document"]["ppn"], "short_title": h["document"]["short_title"]} for h in data]}

# === Agenda, detail en handlers blijven zoals je had ===
# (ik laat die intact want je issue zat in call_assistant / streaming)

# === Routes ===
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/start_thread", methods=["POST"])
def start_thread():
    thread = openai.beta.threads.create()
    logger.info(f"thread_start id={thread.id}")
    return jsonify({"thread_id": thread.id})

@app.route("/send_message", methods=["POST"])
def send_message():
    data = request.json
    tid, user_input = data["thread_id"], data["user_input"]
    active = active_agents.get(tid, "router")

    logger.info(f"send_message thread={tid} active_agent={active}")
    resp_text, tid = call_assistant(active, user_input, tid)
    if not resp_text:
        return error_envelope("OpenAI gaf geen output", tid)

    sq = extract_marker(resp_text, "SEARCH_QUERY:")
    cq = extract_marker(resp_text, "VERGELIJKINGS_QUERY:")
    aq = extract_marker(resp_text, "AGENDA_VRAAG:")

    if sq:
        return handle_search(sq, tid)
    if cq:
        return handle_compare(cq, tid)
    if aq:
        return handle_agenda(aq, tid)
    return jsonify(make_envelope("text", [], None, resp_text, tid))

@app.route("/apply_filters", methods=["POST"])
def apply_filters():
    data = request.json
    tid, filters = data["thread_id"], data["filter_values"]
    logger.info(f"apply_filters thread={tid} values_len={len(filters)}")

    resp_text, tid = call_assistant("router", filters, tid)
    if not resp_text:
        return error_envelope("Geen response voor filters", tid)

    sq = extract_marker(resp_text, "SEARCH_QUERY:")
    cq = extract_marker(resp_text, "VERGELIJKINGS_QUERY:")
    aq = extract_marker(resp_text, "AGENDA_VRAAG:")

    if sq:
        return handle_search(sq, tid)
    if cq:
        return handle_compare(cq, tid)
    if aq:
        return handle_agenda(aq, tid)
    return jsonify(make_envelope("text", [], None, resp_text, tid))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
