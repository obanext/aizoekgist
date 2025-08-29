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
def make_envelope(resp_type, results=None, url=None, message=None, thread_id=None, location=None):
    return {
        "response": {
            "type": resp_type,
            "url": url,
            "message": normalize_message(message),
            "results": results or [],
            "location": location
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

                if cls == "ThreadMessageDelta":
                    for block in ev.data.delta.content:
                        if block.type == "text":
                            response_text += block.text.value

                elif etype == "response.output_text.delta":
                    response_text += ev.delta

            stream.until_done()

        logger.info(f"assistant_done agent={agent_key} thread={thread_id} output_len={len(response_text)}")
        return response_text, thread_id

    except Exception:
        logger.exception("openai_error")
        return "", thread_id

# === Typesense ===
def typesense_search(params, include_fields=None):
    headers = {"Content-Type": "application/json", "X-TYPESENSE-API-KEY": TYPESENSE_API_KEY}

    body = {"searches": [{
        "q": params.get("q"),
        "query_by": params.get("query_by"),
        "collection": params.get("collection"),
        "prefix": "false",
        "vector_query": params.get("vector_query"),
        "include_fields": include_fields or "*",
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

    collection = params.get("collection")
    if collection == COLLECTION_FAQ:
        # FAQ resultaten
        return {"results": [
            {
                "vraag": h["document"].get("vraag"),
                "antwoord": h["document"].get("antwoord")
            } for h in data if h.get("document")
        ]}
    else:
        # Boeken resultaten
        return {"results": [
            {
                "ppn": h["document"].get("ppn"),
                "short_title": h["document"].get("short_title")
            } for h in data if h.get("document")
        ]}


# === Agenda detail ===
def fetch_agenda_results(api_url):
    if "authorization=" not in api_url:
        api_url += ("&" if "?" in api_url else "?") + f"authorization={OBA_API_KEY}"
    r = requests.get(api_url, timeout=15)
    if r.status_code != 200:
        return []
    root = ET.fromstring(r.text)
    out = []
    for res in root.findall(".//result"):
        title = (res.findtext(".//titles/title") or "").strip() or "Geen titel"
        cover = (res.findtext(".//coverimages/coverimage") or "").strip()
        link = (res.findtext(".//custom/evenement/deeplink") or "").strip()
        summary = (res.findtext(".//summaries/summary") or "").strip()
        out.append({"title": title, "cover": cover, "link": link, "summary": summary})
    return out

def fetch_event_detail(nativeid):
    try:
        url_json = f'https://zoeken.oba.nl/api/v1/details/?id=|evenementen|{nativeid}&authorization={OBA_API_KEY}&output=json'
        r_json = requests.get(url_json, timeout=15)
        if r_json.status_code != 200:
            return None
        data = r_json.json().get("record", {})
        title = data.get("titles", [""])[0] if isinstance(data.get("titles"), list) else ""
        summary = data.get("summaries", [""])[0] if isinstance(data.get("summaries"), list) else ""
        cover = data.get("coverimages", [""])[0] if isinstance(data.get("coverimages"), list) else ""
        deeplink = ""
        for c in data.get("custom", []):
            if c.get("type") == "evenement":
                parts = c.get("text", "").split("http")
                if len(parts) == 2:
                    deeplink = "http" + parts[1].strip()
                break
        return {"title": title or "Geen titel", "cover": cover, "link": deeplink, "summary": summary}
    except:
        return None

def build_agenda_results_from_nativeids(nativeids):
    results = []
    for nid in nativeids:
        detail = fetch_event_detail(nid)
        if detail:
            results.append(detail)
    return results

# === Core Handlers ===
def handle_search(query, tid):
    active_agents[tid] = "search"
    resp_text, tid = call_assistant("search", query, tid)

    try:
        params = json.loads(resp_text)
    except:
        return jsonify(make_envelope("text", [], None, resp_text, tid))

    results = typesense_search(params)

    # Kies type op basis van collectie
    resp_type = "faq" if params.get("collection") == COLLECTION_FAQ else "collection"

    return jsonify(make_envelope(
        resp_type,
        results.get("results", []),
        None,
        params.get("Message"),
        tid
    ))

def handle_compare(query, tid):
    active_agents[tid] = "compare"
    resp_text, tid = call_assistant("compare", query, tid)

    try:
        params = json.loads(resp_text)
    except:
        return jsonify(make_envelope("collection", [], None, resp_text, tid))

    results = typesense_search(params)
    return jsonify(make_envelope(
        "collection",
        results.get("results", []),
        None,
        params.get("Message"),
        tid
    ))

def handle_agenda(query, tid):
    active_agents[tid] = "agenda"
    resp_text, tid = call_assistant("agenda", query, tid)
    try:
        agenda_obj = json.loads(resp_text)
    except:
        return jsonify(make_envelope("agenda", [], None, resp_text, tid))

    if "API" in agenda_obj and "URL" in agenda_obj:
        results = fetch_agenda_results(agenda_obj["API"]) or []
        return jsonify(make_envelope("agenda", results, agenda_obj.get("URL"), agenda_obj.get("Message"), tid))

    if agenda_obj.get("collection") == COLLECTION_EVENTS:
        params = {
            "q": agenda_obj.get("q", ""),
            "collection": agenda_obj.get("collection"),
            "query_by": agenda_obj.get("query_by", "embedding"),
            "vector_query": agenda_obj.get("vector_query", "embedding:([], alpha: 0.8)"),
            "filter_by": agenda_obj.get("filter_by", "")
        }
        nativeids = typesense_search(params, include_fields="nativeid")
        results = build_agenda_results_from_nativeids(nativeids if isinstance(nativeids, list) else [])
        first_url = results[0]["link"] if results and results[0].get("link") else ""
        return jsonify(make_envelope("agenda", results, first_url, agenda_obj.get("Message"), tid))

    return jsonify(make_envelope("agenda", [], None, agenda_obj.get("Message"), tid))

# === Routes ===
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/start_thread", methods=["POST"])
def start_thread():
    thread = openai.beta.threads.create()
    return jsonify({"thread_id": thread.id})

@app.route("/send_message", methods=["POST"])
def send_message():
    data = request.json
    tid, user_input = data["thread_id"], data["user_input"]
    active = active_agents.get(tid, "router")

    resp_text, tid = call_assistant(active, user_input, tid)
    if not resp_text:
        return error_envelope("OpenAI gaf geen output", tid)

    if active == "router":
        try:
            obj = json.loads(resp_text)
        except:
            return jsonify(make_envelope("text", [], None, resp_text, tid))

        marker = obj.get("Marker","")
        message = obj.get("Message")

        sq = extract_marker(marker, "SEARCH_QUERY:")
        cq = extract_marker(marker, "VERGELIJKINGS_QUERY:")
        aq = extract_marker(marker, "AGENDA_VRAAG:")

        if sq:
            return handle_search(sq, tid)
        if cq:
            return handle_compare(cq, tid)
        if aq:
            return handle_agenda(aq, tid)

        return jsonify(make_envelope("text", [], None, message or marker, tid))

    try:
        params = json.loads(resp_text)

        if active == "search":
            results = typesense_search(params)
            return jsonify(make_envelope("collection", results.get("results", []), None, params.get("Message"), tid))

        if active == "compare":
            results = typesense_search(params)
            return jsonify(make_envelope("collection", results.get("results", []), None, params.get("Message"), tid))

        if active == "agenda":
            return handle_agenda(json.dumps(params), tid)

    except:
        return jsonify(make_envelope(active, [], None, resp_text, tid))

@app.route("/apply_filters", methods=["POST"])
def apply_filters():
    data = request.json
    tid, filters = data["thread_id"], data["filter_values"]
    resp_text, tid = call_assistant("router", filters, tid)
    if not resp_text:
        return error_envelope("Geen response voor filters", tid)

    try:
        obj = json.loads(resp_text)
    except:
        return jsonify(make_envelope("text", [], None, resp_text, tid))

    marker = obj.get("Marker", "")
    message = obj.get("Message")

    sq = extract_marker(marker, "SEARCH_QUERY:")
    cq = extract_marker(marker, "VERGELIJKINGS_QUERY:")
    aq = extract_marker(marker, "AGENDA_VRAAG:")

    if sq:
        return handle_search(sq, tid)
    if cq:
        return handle_compare(cq, tid)
    if aq:
        return handle_agenda(aq, tid)

    return jsonify(make_envelope("text", [], None, message or marker, tid))

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
    url = f'https://zoeken.oba.nl/api/v1/details/?id=|oba-catalogus|{item_id}&authorization={OBA_API_KEY}&output=json'
    r = requests.get(url, timeout=15)
    if r.headers.get('Content-Type', '').startswith('application/json'):
        return jsonify(r.json()), r.status_code, r.headers.items()
    return r.text, r.status_code, r.headers.items()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
