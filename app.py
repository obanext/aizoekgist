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

# === Collections ===
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

# === OpenAI helpers (streaming + fallback) ===
def _collect_assistant_text(thread_id, max_msgs=10):
    msgs = openai.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=max_msgs)
    for m in msgs.data:
        if getattr(m, "role", "") == "assistant":
            buf = []
            for part in getattr(m, "content", []):
                if getattr(part, "type", "") == "text":
                    buf.append(part.text.value)
            if buf:
                return "".join(buf)
    return ""

def _run_streaming(agent_key, thread_id):
    buf = []
    with openai.beta.threads.runs.stream(
        thread_id=thread_id,
        assistant_id=assistant_ids[agent_key]
    ) as stream:
        for ev in stream:  # context-object is iterabel
            if getattr(ev, "type", "") == "response.output_text.delta":
                buf.append(ev.delta)
        stream.until_done()
    txt = "".join(buf).strip()
    if not txt:
        txt = _collect_assistant_text(thread_id)
    return txt

def _run_and_poll(agent_key, thread_id, timeout_s=60, poll_interval_s=0.5):
    run = openai.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_ids[agent_key]
    )
    start = time.time()
    while True:
        run = openai.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
        if run.status == "completed":
            break
        if run.status in ("failed", "cancelled", "expired"):
            logger.error(f"assistant_run_ended status={run.status} last_error={getattr(run, 'last_error', None)}")
            return ""
        if time.time() - start > timeout_s:
            logger.error("assistant_timeout")
            return ""
        time.sleep(poll_interval_s)
    return _collect_assistant_text(thread_id)

# === OpenAI main call ===
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

        # 1) probeer streaming (preferred)
        try:
            response_text = _run_streaming(agent_key, thread_id)
        except Exception as e:
            logger.warning(f"stream_failed fallback_to_poll err={e}")
            # 2) fallback: poll tot completed
            response_text = _run_and_poll(agent_key, thread_id)

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

# === Agenda: XML API lijst ===
def fetch_agenda_results(api_url):
    if "authorization=" not in api_url:
        api_url += ("&" if "?" in api_url else "?") + f"authorization={OBA_API_KEY}"
    logger.info(f"agenda_fetch url={api_url}")
    r = requests.get(api_url, timeout=15)
    if r.status_code != 200:
        logger.warning(f"agenda_error status={r.status_code}")
        return []
    root = ET.fromstring(r.text)
    out = []
    for res in root.findall(".//result"):
        title = (res.findtext(".//titles/title") or "").strip() or "Geen titel"
        cover = (res.findtext(".//coverimages/coverimage") or "").strip()
        link = (res.findtext(".//custom/evenement/deeplink") or "").strip()
        summary = (res.findtext(".//summaries/summary") or "").strip()

        d_node = res.find(".//custom/gebeurtenis/datum")
        raw_start = d_node.get("start") if d_node is not None else ""
        raw_end = d_node.get("eind") if d_node is not None else ""

        gebouw_node = res.find(".//custom/gebeurtenis/gebouw")
        zaal_node = res.find(".//custom/gebeurtenis/locatienaam")
        gebouw = (gebouw_node.text or "").strip() if gebouw_node is not None else ""
        zaal = (zaal_node.text or "").strip() if zaal_node is not None else ""
        location = f"{gebouw} {zaal}".strip()

        date_str, time_str = "", ""
        if raw_start:
            try:
                dt_start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
                date_str = dt_start.strftime("%A %d %B %Y")
                time_str = dt_start.strftime("%H:%M")
            except:
                pass
        if raw_end:
            try:
                dt_end = datetime.fromisoformat(raw_end.replace("Z", "+00:00"))
                time_str = f"{time_str} - {dt_end.strftime('%H:%M')}".strip()
            except:
                pass

        out.append({
            "title": title,
            "cover": cover,
            "link": link,
            "summary": summary,
            "date": date_str,
            "time": time_str,
            "location": location,
            "raw_date": {"start": raw_start, "end": raw_end}
        })
    logger.info(f"agenda_results count={len(out)}")
    return out

# === Agenda: detail parsing via nativeid ===
def fetch_event_detail(nativeid):
    try:
        # JSON detail
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

        # XML detail
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
        gebouw = gebouw_node.text.strip() if (gebouw_node is not None and gebouw_node.text) else ""
        zaal = zaal_node.text.strip() if (zaal_node is not None and zaal_node.text) else ""
        location = f"{gebouw} {zaal}".strip()

        date_str = ""
        time_str = ""
        if raw_start:
            try:
                dt_start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
                date_str = dt_start.strftime("%A %d %B %Y")
                time_str = dt_start.strftime("%H:%M")
            except:
                pass
        if raw_end:
            try:
                dt_end = datetime.fromisoformat(raw_end.replace("Z", "+00:00"))
                time_str += f" - {dt_end.strftime('%H:%M')}"
            except:
                pass

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
    try:
        params = json.loads(resp_text)
    except:
        return error_envelope(resp_text, tid)
    results = typesense_search(params)
    return jsonify(make_envelope("collection", results.get("results", []), None, None, tid))

def handle_compare(query, tid):
    logger.info(f"handler_compare thread={tid}")
    active_agents[tid] = "compare"
    resp_text, tid = call_assistant("compare", query, tid)
    try:
        params = json.loads(resp_text)
    except:
        return error_envelope(resp_text, tid)
    results = typesense_search(params)
    return jsonify(make_envelope("collection", results.get("results", []), None, None, tid))

def handle_agenda(query, tid):
    logger.info(f"handler_agenda thread={tid}")
    active_agents[tid] = "agenda"
    resp_text, tid = call_assistant("agenda", query, tid)
    try:
        agenda_obj = json.loads(resp_text)
    except:
        return error_envelope(resp_text, tid)

    # Pad 1: directe OBA API URL
    if "API" in agenda_obj and "URL" in agenda_obj:
        results = fetch_agenda_results(agenda_obj["API"])
        return jsonify(make_envelope("agenda", results, agenda_obj.get("URL"), agenda_obj.get("Message"), tid))

    # Pad 2: Typesense nativeid → detail merge
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

# === Debug routes (optioneel) ===
@app.route("/sdk_version")
def sdk_version():
    return {"openai_version": openai.__version__}

@app.route("/stream_probe")
def stream_probe():
    try:
        t = openai.beta.threads.create()
        openai.beta.threads.messages.create(thread_id=t.id, role="user", content="ping")
        try:
            out = _run_streaming("router", t.id)
            return {"mode": "stream", "ok": bool(out), "out_len": len(out)}
        except Exception as e:
            fallback = _run_and_poll("router", t.id, timeout_s=20)
            return {"mode": "poll_fallback", "ok": bool(fallback), "out_len": len(fallback), "stream_err": str(e)}
    except Exception as e:
        return {"mode": "error", "err": str(e)}, 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
