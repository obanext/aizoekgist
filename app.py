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

# Collections verplicht uit ENV
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

active_agents = {}  # {thread_id: role}

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
    if not raw: return None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed.get("Message")
            return raw
        except: return raw
    if isinstance(raw, dict):
        return raw.get("Message")
    return str(raw)

# === OpenAI ===
def call_assistant(agent_key, user_input, thread_id=None):
    try:
        if not thread_id:
            thread = openai.beta.threads.create()
            thread_id = thread.id
            logger.info(f"thread_new id={thread_id}")
        else:
            openai.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_input)

        logger.info(f"assistant_call agent={agent_key} thread={thread_id} input_len={len(user_input)}")

        stream = openai.beta.threads.runs.stream(
            thread_id=thread_id,
            assistant_id=assistant_ids[agent_key]
        )

        response_text = ""
        for event in stream.events():  
            if event.type == "response.output_text.delta":
                response_text += event.delta

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
        return {"error": r.status_code, "message": r.text}
    data = r.json()["results"][0]["hits"]
    if include_fields == "nativeid":
        logger.info(f"typesense_hits events count={len(data)}")
        return [h["document"].get("nativeid") for h in data if h.get("document")] 
    logger.info(f"typesense_hits books count={len(data)}")
    return {"results": [{"ppn": h["document"]["ppn"], "short_title": h["document"]["short_title"]} for h in data]}

# === Agenda detail parsing ===
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

        url_xml = f'https://zoeken.oba.nl/api/v1/details/?id=|evenementen|{nativeid}&authorization={OBA_API_KEY}'
        r_xml = requests.get(url_xml, timeout=15)
        if r_xml.status_code != 200:
            return None
        root = ET.fromstring(r_xml.text)

        d_node = root.find('.//custom/gebeurtenis/datum')
        raw_start = d_node.get('start') if d_node is not None else ""
        raw_end = d_node.get('eind') if d_node is not None else ""

        gebouw_node = root.find('.//custom/gebeurtenis/gebouw')
        zaal_node = root.find('.//custom/gebeurtenis/locatienaam')
        gebouw = gebouw_node.text.strip() if gebouw_node is not None and gebouw_node.text else ""
        zaal = zaal_node.text.strip() if zaal_node is not None and zaal_node.text else ""
        location = f"{gebouw} {zaal}".strip()

        date_str = ""
        time_str = ""
        if raw_start:
            try:
                dt_start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
                date_str = dt_start.strftime("%A %d %B %Y")
                time_str = dt_start.strftime("%H:%M")
            except: pass
        if raw_end:
            try:
                dt_end = datetime.fromisoformat(raw_end.replace("Z", "+00:00"))
                time_str += f" - {dt_end.strftime('%H:%M')}"
            except: pass

        return {
            "title": title or "Geen titel",
            "cover": cover,
            "link": deeplink,
            "summary": summary,
            "date": date_str,
            "time": time_str,
            "location": location,
            "raw_date": {"start": raw_start, "end": raw_end}
        }
    except:
        logger.exception("event_detail_error")
        return None

def build_agenda_results_from_nativeids(nativeids):
    results = []
    for nid in nativeids:
        detail = fetch_event_detail(nid)
        if detail:
            results.append(detail)
    logger.info(f"agenda_build count_in={len(nativeids)} count_out={len(results)}")
    return results

# === Core Handlers ===
def handle_search(query, tid):
    logger.info(f"handler_search thread={tid}")
    active_agents[tid] = "search"
    resp_text, tid = call_assistant("search", query, tid)
    try: params = json.loads(resp_text)
    except: return error_envelope(resp_text, tid)
    results = typesense_search(params)
    return jsonify(make_envelope("collection", results.get("results", []), None, None, tid))

def handle_compare(query, tid):
    logger.info(f"handler_compare thread={tid}")
    active_agents[tid] = "compare"
    resp_text, tid = call_assistant("compare", query, tid)
    try: params = json.loads(resp_text)
    except: return error_envelope(resp_text, tid)
    results = typesense_search(params)
    return jsonify(make_envelope("collection", results.get("results", []), None, None, tid))

def handle_agenda(query, tid):
    logger.info(f"handler_agenda thread={tid}")
    active_agents[tid] = "agenda"
    resp_text, tid = call_assistant("agenda", query, tid)
    try: agenda_obj = json.loads(resp_text)
    except: return error_envelope(resp_text, tid)

    if "API" in agenda_obj and "URL" in agenda_obj:
        results = fetch_agenda_results(agenda_obj["API"])
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
        results = build_agenda_results_from_nativeids(nativeids)
        first_url = results[0]["link"] if results else ""
        return jsonify(make_envelope("agenda", results, first_url, agenda_obj.get("Message"), tid))

    return error_envelope("Agenda format onbekend", tid)

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

    if sq: return handle_search(sq, tid)
    if cq: return handle_compare(cq, tid)
    if aq: return handle_agenda(aq, tid)
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

    if sq: return handle_search(sq, tid)
    if cq: return handle_compare(cq, tid)
    if aq: return handle_agenda(aq, tid)
    return jsonify(make_envelope("text", [], None, resp_text, tid))

# === Proxies ===
@app.route('/proxy/resolver')
def proxy_resolver():
    ppn = request.args.get('ppn')
    url = f'https://zoeken.oba.nl/api/v1/resolver/ppn/?id={ppn}&authorization={OBA_API_KEY}'
    logger.info(f"proxy_resolver url={url}")
    r = requests.get(url, timeout=15)
    return r.content, r.status_code, r.headers.items()

@app.route('/proxy/details')
def proxy_details():
    item_id = request.args.get('item_id')
    url = f'https://zoeken.oba.nl/api/v1/details/?id=|oba-catalogus|{item_id}&authorization={OBA_API_KEY}&output=json'
    logger.info(f"proxy_details url={url}")
    r = requests.get(url, timeout=15)
    if r.headers.get('Content-Type', '').startswith('application/json'):
        return jsonify(r.json()), r.status_code, r.headers.items()
    return r.text, r.status_code, r.headers.items()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
