ik wil dat je percies aangeeft op welke regels ik welke aanpassing ik moet doen:

dit is de huidige app.py:

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
app.secret_key = os.environ.get('SECRET_KEY')

# Env
openai_api_key = os.environ.get('OPENAI_API_KEY')
typesense_api_key = os.environ.get('TYPESENSE_API_KEY')
typesense_api_url = os.environ.get('TYPESENSE_API_URL')
oba_api_key = os.environ.get('OBA_API_KEY')
openai.api_key = openai_api_key

# Assistants
assistant_id_1 = 'asst_ejPRaNkIhjPpNHDHCnoI5zKY'
assistant_id_2 = 'asst_iN7gutrYjI18E97U42GODe4B'
assistant_id_3 = 'asst_NLL8P78p9kUuiq08vzoRQ7tn'
assistant_id_4 = 'asst_9Adxq0d95aUQbMfEGtqJLVx1'

# Logging
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
logger = logging.getLogger('oba_app')
logger.setLevel(getattr(logging, log_level, logging.INFO))
log_handler = logging.StreamHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
if not logger.handlers:
    logger.addHandler(log_handler)
logger.propagate = False


@app.before_request
def _start_timer():
    g.start_time = time.time()


@app.after_request
def _log_response(response):
    try:
        duration = (time.time() - g.start_time) if hasattr(g, 'start_time') else -1
        logger.info(f"http {request.method} {request.path} status={response.status_code} dur_ms={int(duration*1000)}")
    except Exception:
        pass
    return response


@app.errorhandler(Exception)
def _handle_error(e):
    logger.exception(f"unhandled_error path={request.path}")
    return jsonify({'error': 'internal server error'}), 500


# -------- Helpers to parse assistant "routes"
def extract_search_query(response):
    marker = "SEARCH_QUERY:"
    if response and marker in response:
        return response.split(marker, 1)[1].strip()
    return None


def extract_comparison_query(response):
    marker = "VERGELIJKINGS_QUERY:"
    if response and marker in response:
        return response.split(marker, 1)[1].strip()
    return None


def extract_agenda_query(response):
    marker = "AGENDA_VRAAG:"
    if response and marker in response:
        return response.split(marker, 1)[1].strip()
    return None


# -------- Agenda XML fetch (route A)
def fetch_agenda_results(api_url):
    """Haalt agenda-resultaten op (XML) en zet ze om naar cards, met deeplink-only."""
    try:
        if "authorization=" not in api_url:
            api_url += f"&authorization={oba_api_key}"
        logger.info(f"agenda_xml_fetch url={api_url}")
        response = requests.get(api_url, timeout=15)
        response.raise_for_status()
        root = ET.fromstring(response.text)

        results = []
        result_nodes = root.find('results')
        if result_nodes is None:
            logger.info("agenda_xml_no_results")
            return []

        for result in result_nodes.findall('result'):
            title = result.findtext('.//titles/title') or "Geen titel"
            cover = result.findtext('.//coverimages/coverimage') or ""

            # FIX: gebruik ALLEEN deeplink
            deeplink_node = result.find('.//custom/evenement/deeplink')
            link = (deeplink_node.text.strip() if deeplink_node is not None and deeplink_node.text else "#")

            summary = result.findtext('.//summaries/summary') or ""

            # Datum/locatie
            datum_node = result.find('.//custom/gebeurtenis/datum')
            datum_start = datum_node.get('start') if datum_node is not None else None
            datum_eind = datum_node.get('eind') if datum_node is not None else None
            gebouw = result.findtext('.//custom/gebeurtenis/gebouw') or ""
            locatienaam = result.findtext('.//custom/gebeurtenis/locatienaam') or ""

            raw_start = datum_start or ""
            raw_end = datum_eind or ""

            date_str = ""
            time_str = ""
            if raw_start:
                try:
                    dt_start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
                    date_str = dt_start.strftime("%A %d %B %Y")
                    time_str = dt_start.strftime("%H:%M")
                except Exception:
                    pass
            if raw_end:
                try:
                    dt_end = datetime.fromisoformat(raw_end.replace("Z", "+00:00"))
                    time_str += " - " + dt_end.strftime("%H:%M")
                except Exception:
                    pass

            location = f"{gebouw} - {locatienaam}".strip(" -")

            results.append({
                "title": title,
                "cover": cover,
                "link": link,
                "summary": summary,
                "date": date_str,
                "time": time_str,
                "location": location,
                "raw_date": {"start": raw_start, "end": raw_end}
            })

        logger.info(f"agenda_xml_results count={len(results)}")
        return results

    except Exception:
        logger.exception("agenda_xml_error")
        return []


# -------- OpenAI streaming wrapper
class CustomEventHandler(openai.AssistantEventHandler):
    def __init__(self):
        super().__init__()
        self.response_text = ""

    def on_text_created(self, text) -> None:
        self.response_text = ""

    def on_text_delta(self, delta, snapshot):
        self.response_text += delta.value

    def on_tool_call_created(self, tool_call):
        pass

    def on_tool_call_delta(self, delta, snapshot):
        pass


def call_assistant(assistant_id, user_input, thread_id=None):
    try:
        if thread_id is None:
            thread = openai.beta.threads.create()
            thread_id = thread.id
            logger.info(f"openai_new_thread thread_id={thread_id}")
        else:
            openai.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_input)

        logger.info(f"openai_run_start thread_id={thread_id} assistant_id={assistant_id}")
        event_handler = CustomEventHandler()
        with openai.beta.threads.runs.stream(thread_id=thread_id, assistant_id=assistant_id, event_handler=event_handler) as stream:
            stream.until_done()
        logger.info(f"openai_run_done thread_id={thread_id} len={len(event_handler.response_text)}")
        return event_handler.response_text, thread_id

    except Exception:
        logger.exception("openai_error")
        return "ERROR: OpenAI call failed.", thread_id


# -------- Typesense parsing & calls
def parse_assistant_message(content):
    try:
        parsed = json.loads(content)
        return {
            "q": parsed.get("q", ""),
            "query_by": parsed.get("query_by", ""),
            "collection": parsed.get("collection", ""),
            "vector_query": parsed.get("vector_query", ""),
            "filter_by": parsed.get("filter_by", "")
        }
    except json.JSONDecodeError:
        logger.warning("parse_assistant_message_json_error")
        return None


def perform_typesense_search(params):
    headers = {'Content-Type': 'application/json', 'X-TYPESENSE-API-KEY': typesense_api_key}
    body = {
        "searches": [{
            "q": params["q"],
            "query_by": params["query_by"],
            "collection": params["collection"],
            "prefix": "false",
            "vector_query": params["vector_query"],
            "include_fields": "short_title,ppn",
            "per_page": 15,
            "filter_by": params["filter_by"]
        }]}
    logger.info(f"typesense_books_request collection={params.get('collection')} q_len={len(params.get('q',''))}")
    response = requests.post(typesense_api_url, headers=headers, json=body, timeout=15)
    logger.info(f"typesense_books_response status={response.status_code}")
    if response.status_code == 200:
        data = response.json()
        hits = data["results"][0]["hits"]
        logger.info(f"typesense_books_hits count={len(hits)}")
        return {"results": [{"ppn": h["document"]["ppn"], "short_title": h["document"]["short_title"]} for h in hits]}
    else:
        logger.warning(f"typesense_books_error status={response.status_code}")
        return {"error": response.status_code, "message": response.text}


def perform_typesense_search_events(params):
    headers = {'Content-Type': 'application/json', 'X-TYPESENSE-API-KEY': typesense_api_key}
    body = {
        "searches": [{
            "q": params["q"],
            "query_by": params["query_by"],
            "collection": params["collection"],
            "prefix": "false",
            "vector_query": params["vector_query"],
            "include_fields": "nativeid",
            "per_page": 15,
            "filter_by": params["filter_by"]
        }]}
    logger.info(f"typesense_events_request collection={params.get('collection')} q_len={len(params.get('q',''))}")
    response = requests.post(typesense_api_url, headers=headers, json=body, timeout=15)
    logger.info(f"typesense_events_response status={response.status_code}")
    if response.status_code == 200:
        data = response.json()
        hits = data["results"][0]["hits"]
        # Support zowel `nativeid` als `native_id` in Typesense document
        nativeids = [
            h["document"].get("nativeid") or h["document"].get("native_id")
            for h in hits
            if h.get("document") and (h["document"].get("nativeid") or h["document"].get("native_id"))
        ]
        logger.info(f"typesense_events_hits count={len(hits)} nativeids={len(nativeids)}")
        return nativeids
    else:
        logger.warning(f"typesense_events_error status={response.status_code}")
        return []


# -------- Event detail JSON/XML response
def fetch_event_detail(nativeid):
    try:
        # JSON-endpoint (zonder datum)
        url_json = f'https://zoeken.oba.nl/api/v1/details/?id=|evenementen|{nativeid}&authorization={oba_api_key}&output=json'
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

        # XML-endpoint (voor datum en locatie)
        url_xml = f'https://zoeken.oba.nl/api/v1/details/?id=|evenementen|{nativeid}&authorization={oba_api_key}'
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
    logger.info(f"agenda_build_from_nativeids count_in={len(nativeids)} count_out={len(results)}")
    return results


# -------- Routes
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/start_thread', methods=['POST'])
def start_thread():
    try:
        thread = openai.beta.threads.create()
        logger.info(f"start_thread thread_id={thread.id}")
        return jsonify({'thread_id': thread.id})
    except Exception as e:
        logger.exception("start_thread_error")
        return jsonify({'error': str(e)}), 500


@app.route('/send_message', methods=['POST'])
def send_message():
    try:
        data = request.json
        thread_id = data['thread_id']
        user_input = data['user_input']
        assistant_id = data['assistant_id']
        logger.info(f"send_message_in thread_id={thread_id} assistant_id={assistant_id} text_len={len(user_input)}")

        response_text, thread_id = call_assistant(assistant_id, user_input, thread_id)
        search_query = extract_search_query(response_text)
        comparison_query = extract_comparison_query(response_text)
        agenda_query = extract_agenda_query(response_text)
        logger.info(f"send_message_paths search={bool(search_query)} compare={bool(comparison_query)} agenda={bool(agenda_query)}")

        if search_query:
            response_text_2, thread_id = call_assistant(assistant_id_2, search_query, thread_id)
            search_params = parse_assistant_message(response_text_2)
            logger.info(f"search_params_present={bool(search_params)}")
            if search_params:
                coll = search_params.get("collection")
                logger.info(f"collection={coll}")
                if coll == "obadbevents13825":   # <-- Pas aan indien je een andere events-collectie gebruikt
                    nativeids = perform_typesense_search_events(search_params)
                    agenda_results = build_agenda_results_from_nativeids(nativeids)
                    first_url = agenda_results[0]["link"] if agenda_results else ""
                    logger.info(f"agenda_results_count={len(agenda_results)}")
                    return jsonify({
                        'response': {
                            'type': 'agenda',
                            'url': first_url,
                            'message': "Is dit wat je zoekt of ben je op zoek naar iets anders?",
                            'results': agenda_results
                        },
                        'thread_id': thread_id
                    })
                return jsonify({'response': perform_typesense_search(search_params), 'thread_id': thread_id})
            return jsonify({'response': response_text_2, 'thread_id': thread_id})

        elif comparison_query:
            response_text_3, thread_id = call_assistant(assistant_id_3, comparison_query, thread_id)
            search_params = parse_assistant_message(response_text_3)
            logger.info(f"compare_params_present={bool(search_params)}")
            if search_params:
                coll = search_params.get("collection")
                logger.info(f"collection={coll}")
                if coll == "obadbevents13825":
                    nativeids = perform_typesense_search_events(search_params)
                    agenda_results = build_agenda_results_from_nativeids(nativeids)
                    first_url = agenda_results[0]["link"] if agenda_results else ""
                    logger.info(f"agenda_results_count={len(agenda_results)}")
                    return jsonify({
                        'response': {
                            'type': 'agenda',
                            'url': first_url,
                            'message': "Is dit wat je zoekt of ben je op zoek naar iets anders?",
                            'results': agenda_results
                        },
                        'thread_id': thread_id
                    })
                return jsonify({'response': perform_typesense_search(search_params), 'thread_id': thread_id})
            return jsonify({'response': response_text_3, 'thread_id': thread_id})

        elif agenda_query:
            response_text_4, thread_id = call_assistant(assistant_id_4, agenda_query, thread_id)
            try:
                agenda_obj = json.loads(response_text_4)
            except json.JSONDecodeError:
                logger.warning("agenda_json_decode_error")
                return jsonify({'response': response_text_4, 'thread_id': thread_id})

            logger.info(f"agenda_detect keys={list(agenda_obj.keys())}")

            # Route A: directe API/URL van agent
            if "API" in agenda_obj and "URL" in agenda_obj:
                logger.info("agenda_path=A")
                results = fetch_agenda_results(agenda_obj["API"])
                return jsonify({
                    'response': {
                        'type': 'agenda',
                        'url': agenda_obj.get("URL", ""),
                        'message': agenda_obj.get("Message", "Is dit wat je zoekt of ben je op zoek naar iets anders?"),
                        'results': results
                    },
                    'thread_id': thread_id
                })

            # Route B: Typesense query object van agent
            if "q" in agenda_obj and "collection" in agenda_obj:
                logger.info("agenda_path=B")
                params = {
                    "q": agenda_obj.get("q", ""),
                    "collection": agenda_obj.get("collection", ""),
                    "query_by": agenda_obj.get("query_by", "embedding"),
                    "vector_query": agenda_obj.get("vector_query", "embedding:([], alpha: 0.8)"),
                    "filter_by": agenda_obj.get("filter_by", "")
                }
                if params["collection"] == "obadbevents13825":  # <-- Pas aan indien je een andere events-collectie gebruikt
                    nativeids = perform_typesense_search_events(params)
                    agenda_results = build_agenda_results_from_nativeids(nativeids)
                    first_url = agenda_results[0]["link"] if agenda_results else ""
                    return jsonify({
                        'response': {
                            'type': 'agenda',
                            'url': first_url,
                            'message': agenda_obj.get("Message", "Is dit wat je zoekt of ben je op zoek naar iets anders?"),
                            'results': agenda_results
                        },
                        'thread_id': thread_id
                    })
                logger.info("agenda_b_not_events_collection")
                return jsonify({
                    'response': {
                        'type': 'agenda',
                        'url': "",
                        'message': "Geen events-collectie gevonden.",
                        'results': []
                    },
                    'thread_id': thread_id
                })

            logger.warning("agenda_unknown_format")
            return jsonify({'response': response_text_4, 'thread_id': thread_id})

        logger.info("send_message_fallback_text")
        return jsonify({'response': response_text, 'thread_id': thread_id})

    except Exception as e:
        logger.exception("send_message_error")
        return jsonify({'error': str(e)}), 500


@app.route('/apply_filters', methods=['POST'])
def apply_filters():
    try:
        data = request.json
        thread_id = data['thread_id']
        filter_values = data['filter_values']
        assistant_id = data['assistant_id']
        logger.info(f"apply_filters_in thread_id={thread_id} assistant_id={assistant_id} filters_len={len(filter_values)}")

        response_text, thread_id = call_assistant(assistant_id, filter_values, thread_id)
        search_query = extract_search_query(response_text)
        comparison_query = extract_comparison_query(response_text)
        logger.info(f"apply_filters_paths search={bool(search_query)} compare={bool(comparison_query)}")

        if search_query:
            response_text_2, thread_id = call_assistant(assistant_id_2, search_query, thread_id)
            search_params = parse_assistant_message(response_text_2)
            logger.info(f"apply_filters_params_present={bool(search_params)}")
            if search_params:
                coll = search_params.get("collection")
                logger.info(f"collection={coll}")
                if coll == "obadbevents13825":  # <-- Pas aan indien je een andere events-collectie gebruikt
                    nativeids = perform_typesense_search_events(search_params)
                    agenda_results = build_agenda_results_from_nativeids(nativeids)
                    logger.info(f"agenda_results_count={len(agenda_results)}")
                    return jsonify({
                        'response': {
                            'type': 'agenda',
                            'url': (agenda_results[0]["link"] if agenda_results else ""),
                            'message': "Is dit wat je zoekt of ben je op zoek naar iets anders?",
                            'results': agenda_results
                        },
                        'thread_id': thread_id
                    })
                results = perform_typesense_search(search_params)
                return jsonify({'results': results.get('results', []), 'thread_id': thread_id})
            return jsonify({'response': response_text_2, 'thread_id': thread_id})

        elif comparison_query:
            response_text_3, thread_id = call_assistant(assistant_id_3, comparison_query, thread_id)
            search_params = parse_assistant_message(response_text_3)
            logger.info(f"apply_filters_compare_params_present={bool(search_params)}")
            if search_params:
                coll = search_params.get("collection")
                logger.info(f"collection={coll}")
                if coll == "obadbevents13825":  # <-- Pas aan indien je een andere events-collectie gebruikt
                    nativeids = perform_typesense_search_events(search_params)
                    agenda_results = build_agenda_results_from_nativeids(nativeids)
                    logger.info(f"agenda_results_count={len(agenda_results)}")
                    return jsonify({
                        'response': {
                            'type': 'agenda',
                            'url': (agenda_results[0]["link"] if agenda_results else ""),
                            'message': "Is dit wat je zoekt of ben je op zoek naar iets anders?",
                            'results': agenda_results
                        },
                        'thread_id': thread_id
                    })
                results = perform_typesense_search(search_params)
                return jsonify({'results': results.get('results', []), 'thread_id': thread_id})
            return jsonify({'response': response_text_3, 'thread_id': thread_id})

        logger.info("apply_filters_fallback_text")
        return jsonify({'response': response_text, 'thread_id': thread_id})

    except Exception:
        logger.exception("apply_filters_error")
        return jsonify({'error': str(e)}), 500


# -------- Proxies voor boeken (PPN -> item_id -> details)
@app.route('/proxy/resolver', methods=['GET'])
def proxy_resolver():
    ppn = request.args.get('ppn')
    url = f'https://zoeken.oba.nl/api/v1/resolver/ppn/?id={ppn}&authorization={oba_api_key}'
    logger.info(f"proxy_resolver url={url}")
    response = requests.get(url, timeout=15)
    return response.content, response.status_code, response.headers.items()


@app.route('/proxy/details', methods=['GET'])
def proxy_details():
    item_id = request.args.get('item_id')
    url = f'https://zoeken.oba.nl/api/v1/details/?id=|oba-catalogus|{item_id}&authorization={oba_api_key}&output=json'
    logger.info(f"proxy_details url={url}")
    response = requests.get(url, timeout=15)
    if response.headers.get('Content-Type', '').startswith('application/json'):
        return jsonify(response.json()), response.status_code, response.headers.items()
    return response.text, response.status_code, response.headers.items()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

en de huidige js

let thread_id = null;
let timeoutHandle = null;
let previousResults = [];
let linkedPPNs = new Set();

/* ===== Mobiele helpers: panel state, overlay, history ===== */
function openFilterPanel(pushHistory = true) {
    const panel = document.getElementById('filter-section');
    const other = document.getElementById('result-section');
    other.classList.remove('open');
    panel.classList.add('open');
    document.body.classList.add('panel-open');
    updateActionButtons();
    if (pushHistory) history.pushState({ panel: 'filters' }, '', '#filters');
}

function openResultPanel(pushHistory = true) {
    const panel = document.getElementById('result-section');
    const other = document.getElementById('filter-section');
    other.classList.remove('open');
    panel.classList.add('open');
    document.body.classList.add('panel-open');
    updateActionButtons();
    if (pushHistory) history.pushState({ panel: 'results' }, '', '#results');
}

function closeFilterPanel(useHistoryBack = false) {
    const panel = document.getElementById('filter-section');
    panel.classList.remove('open');
    if (!document.getElementById('result-section').classList.contains('open')) {
        document.body.classList.remove('panel-open');
    }
    updateActionButtons();
    if (useHistoryBack && history.state && history.state.panel === 'filters') {
        history.back();
    }
}

function closeResultPanel(useHistoryBack = false) {
    const panel = document.getElementById('result-section');
    panel.classList.remove('open');
    if (!document.getElementById('filter-section').classList.contains('open')) {
        document.body.classList.remove('panel-open');
    }
    updateActionButtons();
    if (useHistoryBack && history.state && history.state.panel === 'results') {
        history.back();
    }
}

function closeAnyPanel() {
    const hasOpen = document.getElementById('filter-section').classList.contains('open') ||
                    document.getElementById('result-section').classList.contains('open');
    closeFilterPanel();
    closeResultPanel();
    if (hasOpen && history.state && history.state.panel) {
        history.back();
    }
}

/* History: initial state + popstate handler */
(function initHistory() {
    if (!history.state) {
        history.replaceState({ panel: 'chat' }, '', location.pathname);
    }
    window.addEventListener('popstate', (e) => {
        const state = e.state || { panel: 'chat' };
        const isFilters = state.panel === 'filters';
        const isResults = state.panel === 'results';
        if (isFilters) {
            openFilterPanel(false);
        } else if (isResults) {
            openResultPanel(false);
        } else {
            closeFilterPanel();
            closeResultPanel();
            document.body.classList.remove('panel-open');
        }
        updateActionButtons();
    });
})();

/* Swipe-gestures (mobiel) */
let touchStartX = 0;
let touchStartY = 0;
let touchActivePanel = null;
const EDGE_GUTTER = 24;
const SWIPE_THRESH_X = 60;
const SWIPE_MAX_Y = 50;

function onTouchStart(e) {
    if (!e.touches || e.touches.length !== 1) return;
    const t = e.touches[0];
    touchStartX = t.clientX;
    touchStartY = t.clientY;

    const resOpen = document.getElementById('result-section').classList.contains('open');
    const filOpen = document.getElementById('filter-section').classList.contains('open');
    touchActivePanel = resOpen ? 'results' : (filOpen ? 'filters' : 'chat');
}
function onTouchEnd(e) {
    if (!touchStartX && !touchStartY) return;

    const touch = (e.changedTouches && e.changedTouches[0]) || (e.touches && e.touches[0]);
    if (!touch) return;

    const dx = touch.clientX - touchStartX;
    const dy = touch.clientY - touchStartY;
    const absX = Math.abs(dx);
    const absY = Math.abs(dy);

    const vw = window.innerWidth;
    const nearLeftEdge = touchStartX <= EDGE_GUTTER;
    const nearRightEdge = touchStartX >= (vw - EDGE_GUTTER);

    if (absX < SWIPE_THRESH_X || absY > SWIPE_MAX_Y) {
        touchStartX = touchStartY = 0;
        return;
    }

    if (touchActivePanel === 'chat') {
        if (dx > 0 && nearLeftEdge) {
            openResultPanel();
        } else if (dx < 0 && nearRightEdge) {
            openFilterPanel();
        }
    } else if (touchActivePanel === 'results') {
        if (dx < 0) {
            closeResultPanel(true);
        }
    } else if (touchActivePanel === 'filters') {
        if (dx > 0) {
            closeFilterPanel(true);
        }
    }

    touchStartX = touchStartY = 0;
}
document.addEventListener('touchstart', onTouchStart, { passive: true });
document.addEventListener('touchend', onTouchEnd, { passive: true });

/* ===== Functionaliteit chat en zoekresultaten ===== */
function checkInput() {
    const userInput = document.getElementById('user-input').value.trim();
    const sendButton = document.getElementById('send-button');
    const applyFiltersButton = document.getElementById('apply-filters-button');
    const checkboxes = document.querySelectorAll('#filters input[type="checkbox"]');
    let anyChecked = Array.from(checkboxes).some(checkbox => checkbox.checked);

    sendButton.disabled = userInput === "";
    sendButton.style.backgroundColor = userInput === "" ? "#ccc" : "#6d5ab0";
    sendButton.style.cursor = userInput === "" ? "not-allowed" : "pointer";

    applyFiltersButton.disabled = !anyChecked;
    applyFiltersButton.style.backgroundColor = anyChecked ? "#6d5ab0" : "#ccc";
    applyFiltersButton.style.cursor = anyChecked ? "pointer" : "not-allowed";
}

function updateActionButtons() {
    const resultsBtn = document.getElementById('open-results-btn');
    const filtersBtn = document.getElementById('open-filters-btn');
    const backBtn = document.getElementById('back-chat-btn');

    const hasResults = Array.isArray(previousResults) && previousResults.length > 0;
    const resultOpen = document.getElementById('result-section').classList.contains('open');
    const filterOpen = document.getElementById('filter-section').classList.contains('open');

    // standaard
    resultsBtn.style.display = 'none';
    filtersBtn.style.display = 'none';
    backBtn.style.display = 'none';

    if (filterOpen) {
        // filter open → toon loep (back) + results
        backBtn.style.display = 'inline-flex';
        backBtn.onclick = () => closeFilterPanel(true);
        resultsBtn.style.display = 'inline-flex';
        resultsBtn.disabled = !hasResults;
    } else if (resultOpen) {
        // results open → toon loep (back) + filters
        backBtn.style.display = 'inline-flex';
        backBtn.onclick = () => closeResultPanel(true);
        filtersBtn.style.display = 'inline-flex';
        filtersBtn.disabled = !hasResults;
    } else {
        // geen overlay → toon results + filters
        resultsBtn.disabled = !hasResults;
        filtersBtn.disabled = !hasResults;
        resultsBtn.style.display = 'inline-flex';
        filtersBtn.style.display = 'inline-flex';
    }
}



async function startThread() {
    const response = await fetch('/start_thread', { method: 'POST' });
    const data = await response.json();
    thread_id = data.thread_id;
}

async function sendMessage() {
    const userInput = document.getElementById('user-input').value.trim();
    console.log("User Input:", userInput);
    if (userInput === "") return;

    displayUserMessage(userInput);
    showLoader();

    document.getElementById('user-input').value = '';
    checkInput();

    document.getElementById('search-results').style.display = 'grid';
    document.getElementById('detail-container').style.display = 'none';
    document.getElementById('breadcrumbs').innerHTML = '';

    timeoutHandle = setTimeout(() => { showErrorMessage(); }, 30000);

    try {
        const response = await fetch('/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                thread_id: thread_id,
                user_input: userInput,
                assistant_id: 'asst_ejPRaNkIhjPpNHDHCnoI5zKY'
            })
        });
        if (!response.ok) {
            showErrorMessage();
            return;
        }
        const data = await response.json();
        console.log("Backend Response:", data);
        hideLoader();
        clearTimeout(timeoutHandle);

        if (data.response && data.response.type === 'agenda') {
            if (data.response.url) {
                displayAssistantMessage(`<a href="${data.response.url}" target="_blank">${data.response.url}</a>`);
            }
            if (data.response.message) {
                displayAssistantMessage(data.response.message);
            }
            previousResults = data.response.results || [];
            displayAgendaResults(previousResults);
            await sendStatusKlaar();
            return;
        }

        if (!data.response?.results) {
            console.log("Assistant Message:", data.response);
            displayAssistantMessage(data.response);
        }

        if (data.thread_id) {
            thread_id = data.thread_id;
        }

        if (data.response?.results) {
            console.log("Assistant Message:", data.response);
            previousResults = data.response.results;
            displaySearchResults(previousResults);
            await sendStatusKlaar();
        }

        resetFilters();
    } catch (error) {
        showErrorMessage();
    }

    checkInput();
    scrollToBottom();
}

function resetThread() {
    startThread();
    document.getElementById('messages').innerHTML = '';
    document.getElementById('search-results').innerHTML = '';
    document.getElementById('breadcrumbs').innerHTML = 'resultaten';
    document.getElementById('user-input').placeholder = "Welk boek zoek je? Of informatie over..?";
    addOpeningMessage();
    addPlaceholders();
    scrollToBottom();
    resetFilters();
    linkedPPNs.clear();
    updateActionButtons();
}

async function sendStatusKlaar() {
    try {
        const response = await fetch('/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                thread_id: thread_id,
                user_input: 'STATUS : KLAAR',
                assistant_id: 'asst_ejPRaNkIhjPpNHDHCnoI5zKY'
            })
        });
        const data = await response.json();
        displayAssistantMessage(data.response);
        scrollToBottom();
    } catch (error) {}
}

function displayUserMessage(message) {
    const messageContainer = document.getElementById('messages');
    const messageElement = document.createElement('div');
    messageElement.classList.add('user-message');
    messageElement.textContent = message;
    messageContainer.appendChild(messageElement);
    scrollToBottom();
}

function displayAssistantMessage(message) {
    const messageContainer = document.getElementById('messages');
    const messageElement = document.createElement('div');
    messageElement.classList.add('assistant-message');
    if (typeof message === 'object') {
        messageElement.textContent = JSON.stringify(message);
    } else {
        messageElement.innerHTML = message;
    }
    messageContainer.appendChild(messageElement);
    scrollToBottom();
}

function displaySearchResults(results) {
    const searchResultsContainer = document.getElementById('search-results');
    searchResultsContainer.classList.remove('agenda-list');
    searchResultsContainer.classList.add('book-grid');
    searchResultsContainer.innerHTML = '';

    results.forEach(result => {
        const resultElement = document.createElement('div');
        resultElement.classList.add('search-result');
        resultElement.innerHTML = `
            <div onclick="fetchAndShowDetailPage('${result.ppn}')">
                <img src="https://cover.biblion.nl/coverlist.dll/?doctype=morebutton&bibliotheek=oba&style=0&ppn=${result.ppn}&isbn=&lid=&aut=&ti=&size=150" 
                     alt="Cover for PPN ${result.ppn}" 
                     class="book-cover">
                <p>${result.short_title}</p>
            </div>
        `;
        searchResultsContainer.appendChild(resultElement);
    });

    updateResultsBadge(results.length);
    updateActionButtons();
}

function displayAgendaResults(results) {
    const searchResultsContainer = document.getElementById('search-results');
    searchResultsContainer.innerHTML = '';
    searchResultsContainer.classList.remove('book-grid');
    searchResultsContainer.classList.add('agenda-list');

    const maxItems = 5;
    const limitedResults = results.slice(0, maxItems);

    limitedResults.forEach(result => {
        let formattedDate = result.date || 'Datum niet beschikbaar';
        let formattedTime = result.time || '';

        if ((!formattedDate || !formattedTime) && result.raw_date && result.raw_date.start) {
            const startDate = new Date(result.raw_date.start);
            formattedDate = formattedDate || startDate.toLocaleDateString('nl-NL', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
            formattedTime = formattedTime || startDate.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' });
        }
        if ((!formattedTime) && result.raw_date && result.raw_date.end) {
            const endDate = new Date(result.raw_date.end);
            formattedTime = (formattedTime ? (formattedTime + ' - ') : '') + endDate.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' });
        }

        const location = result.location || 'Locatie niet beschikbaar';
        const title = result.title || 'Geen titel beschikbaar';
        const summary = result.summary || 'Geen beschrijving beschikbaar';
        const coverImage = result.cover || '';
        const link = result.link || '#';

        const el = document.createElement('div');
        el.classList.add('agenda-card');
        el.innerHTML = `
            <a href="${link}" target="_blank" class="agenda-card-link">
                <img src="${coverImage}" alt="Agenda cover" class="agenda-card-image">
                <div class="agenda-card-text">
                    <div class="agenda-date">${formattedDate}</div>
                    <div class="agenda-time">${formattedTime}</div>
                    <div class="agenda-title">${title}</div>
                    <div class="agenda-location">${location}</div>
                    <div class="agenda-summary">${summary}</div>
                </div>
            </a>
        `;
        searchResultsContainer.appendChild(el);
    });

    if (results.length > maxItems) {
        const moreButton = document.createElement('button');
        moreButton.classList.add('more-button');
        moreButton.innerHTML = 'Meer';
        moreButton.onclick = () => {
            const url = results[0].link || '#';
            window.open(url, '_blank');
        };
        searchResultsContainer.appendChild(moreButton);
    }

    updateResultsBadge(results.length);
    updateActionButtons();
}

function updateResultsBadge(count) {
    const badge = document.getElementById('results-badge');
    const btn = document.getElementById('open-results-btn');
    if (!badge || !btn) return;

    badge.textContent = count;
    badge.style.display = count > 0 ? 'inline-block' : 'none';

    if (count > 0) {
        btn.classList.add('enlarged');
        setTimeout(() => {
            btn.classList.remove('enlarged');
        }, 2000);
    }
}

function showAgendaDetail(result) {
    const detailContainer = document.getElementById('detail-container');
    detailContainer.innerHTML = `
        <div class="detail-container">
            <img src="${result.cover}" alt="Agenda cover" class="detail-cover">
            <div class="detail-summary">
                <h3>${result.title}</h3>
                <div class="detail-buttons">
                    <button onclick="window.open('${result.link}', '_blank')">Bekijk op OBA.nl</button>
                </div>
            </div>
        </div>
    `;
    detailContainer.style.display = 'flex';
}

async function fetchAndShowDetailPage(ppn) {
    try {
        const resolverResponse = await fetch(`/proxy/resolver?ppn=${ppn}`);
        const resolverText = await resolverResponse.text();
        const parser = new DOMParser();
        const resolverDoc = parser.parseFromString(resolverText, "application/xml");
        const itemIdElement = resolverDoc.querySelector('itemid');
        if (!itemIdElement) {
            throw new Error('Item ID not found in resolver response.');
        }
        const itemId = itemIdElement.textContent.split('|')[2];

        const detailResponse = await fetch(`/proxy/details?item_id=${itemId}`);
        const contentType = detailResponse.headers.get("content-type");
        if (contentType && contentType.indexOf("application/json") !== -1) {
            const detailJson = await detailResponse.json();

            const title = detailJson.record.titles[0] || 'Titel niet beschikbaar';
            const summary = detailJson.record.summaries[0] || 'Samenvatting niet beschikbaar';
            const coverImage = detailJson.record.coverimages[0] || '';

            const detailContainer = document.getElementById('detail-container');
            const searchResultsContainer = document.getElementById('search-results');
            
            searchResultsContainer.style.display = 'none';
            detailContainer.style.display = 'block';

            detailContainer.innerHTML = `
                <div class="detail-container">
                    <img src="${coverImage}" alt="Cover for PPN ${ppn}" class="detail-cover">
                    <div class="detail-summary">
                        <p>${summary}</p>
                        <div class="detail-buttons">
                            <button onclick="goBackToResults()">Terug</button>
                            <button onclick="window.open('https://oba.nl/nl/collectie/oba-collectie?id=' + encodeURIComponent('|oba-catalogus|' + '${itemId}'), '_blank')">Meer informatie op OBA.nl</button>
                            <button onclick="window.open('https://iguana.oba.nl/iguana/www.main.cls?sUrl=search&theme=OBA#app=Reserve&ppn=${ppn}', '_blank')">Reserveer</button>
                        </div>
                    </div>
                </div>
            `;

            const currentUrl = window.location.href.split('?')[0];
            const breadcrumbs = document.getElementById('breadcrumbs');
            breadcrumbs.innerHTML = `<a href="#" onclick="goBackToResults()">resultaten</a> > <span class="breadcrumb-title"><a href="${currentUrl}?ppn=${ppn}" target="_blank">${title}</a></span>`;
            
            if (!linkedPPNs.has(ppn)) {
                sendDetailPageLinkToUser(title, currentUrl, ppn);
            }
        } else {
            throw new Error('Unexpected response content type');
        }
    } catch (error) {
        displayAssistantMessage('Er is iets misgegaan bij het ophalen van de detailpagina.');
    }
}

function goBackToResults() {
    const detailContainer = document.getElementById('detail-container');
    const searchResultsContainer = document.getElementById('search-results');
    detailContainer.style.display = 'none';
    searchResultsContainer.style.display = 'grid';
    displaySearchResults(previousResults);
    document.getElementById('breadcrumbs').innerHTML = '';
}

function sendDetailPageLinkToUser(title, baseUrl, ppn) {
    if (linkedPPNs.has(ppn)) return;
    const message = `Titel: <a href="#" onclick="fetchAndShowDetailPage('${ppn}'); return false;">${title}</a>`;
    displayAssistantMessage(message);
    linkedPPNs.add(ppn);
}

async function applyFiltersAndSend() {
    const checkboxes = document.querySelectorAll('#filters input[type="checkbox"]');
    let selectedFilters = [];
    checkboxes.forEach(checkbox => {
        if (checkbox.checked) {
            selectedFilters.push(checkbox.value);
        }
    });
    const filterString = selectedFilters.join('||');
    if (filterString === "") return;

    displayUserMessage(`Filters toegepast: ${filterString}`);
    showLoader();

    document.getElementById('search-results').style.display = 'grid';
    document.getElementById('detail-container').style.display = 'none';
    document.getElementById('breadcrumbs').innerHTML = '';

    try {
        const response = await fetch('/apply_filters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                thread_id: thread_id,
                filter_values: filterString,
                assistant_id: 'asst_ejPRaNkIhjPpNHDHCnoI5zKY'
            })
        });

        if (!response.ok) {
            hideLoader();
            return;
        }

        const data = await response.json();
        hideLoader();

        if (data.response && data.response.type === 'agenda') {
            previousResults = data.response.results || [];
            displayAgendaResults(previousResults);
            await sendStatusKlaar();
        } else if (data.results) {
            previousResults = data.results;
            displaySearchResults(previousResults);
            await sendStatusKlaar();
        }

        if (data.thread_id) {
            thread_id = data.thread_id;
        }

        resetFilters();

        if (window.innerWidth <= 768) {
            document.getElementById('filter-section').classList.remove('open');
            document.getElementById('result-section').classList.remove('open');
            document.body.classList.remove('panel-open');
            history.replaceState({ panel: 'chat' }, '', location.pathname);
            updateActionButtons();
        }

    } catch (error) {
        hideLoader();
    }

    checkInput();
}

function startNewChat() {
    startThread();
    document.getElementById('messages').innerHTML = '';
    document.getElementById('search-results').innerHTML = '';
    document.getElementById('detail-container').style.display = 'none';
    document.getElementById('breadcrumbs').innerHTML = 'resultaten';
    document.getElementById('user-input').placeholder = "Welk boek zoek je? Of informatie over..?";
    addOpeningMessage();
    addPlaceholders();
    scrollToBottom();
    resetFilters();
    linkedPPNs.clear();
    updateActionButtons();
}

async function startHelpThread() {
    await startThread();
    document.getElementById('messages').innerHTML = '';
    document.getElementById('search-results').innerHTML = '';
    document.getElementById('breadcrumbs').innerHTML = 'resultaten';
    resetFilters();
    linkedPPNs.clear();
    addPlaceholders();
    addOpeningMessage();
    const userMessage = "help";
    displayUserMessage(userMessage);
    await sendHelpMessage(userMessage);
}

async function sendHelpMessage(message) {
    showLoader();
    try {
        const response = await fetch('/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                thread_id: thread_id,
                user_input: message,
                assistant_id: 'asst_ejPRaNkIhjPpNHDHCnoI5zKY'
            })
        });
        if (!response.ok) {
            throw new Error('Het verzenden van het help-bericht is mislukt.');
        }
        const data = await response.json();
        hideLoader();
        if (data.response) {
            displayAssistantMessage(data.response);
        }
    } catch (error) {
        hideLoader();
        displayAssistantMessage('Er is iets misgegaan. Probeer opnieuw.');
    }
}

function extractSearchQuery(response) {
    const searchMarker = "SEARCH_QUERY:";
    if (response.includes(searchMarker)) {
        return response.split(searchMarker)[1].trim();
    }
    return null;
}

function resetFilters() {
    const checkboxes = document.querySelectorAll('#filters input[type="checkbox"]');
    checkboxes.forEach(checkbox => { checkbox.checked = false; });
    checkInput();
}

function showLoader() {
    const messageContainer = document.getElementById('messages');
    const loaderElement = document.createElement('div');
    loaderElement.classList.add('assistant-message', 'loader');
    loaderElement.id = 'loader';
    loaderElement.innerHTML = '<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span>';
    messageContainer.appendChild(loaderElement);
    scrollToBottom();
}

function hideLoader() {
    const loaderElement = document.getElementById('loader');
    if (loaderElement) { loaderElement.remove(); }
    const sendButton = document.getElementById('send-button');
    sendButton.disabled = false;
    sendButton.style.backgroundColor = "#6d5ab0";
    sendButton.style.cursor = "pointer";
}

function scrollToBottom() {
    const messageContainer = document.getElementById('messages');
    messageContainer.scrollTop = messageContainer.scrollHeight;
}

function addOpeningMessage() {
    const openingMessage = "Hoi! Ik ben Nexi, ik ben een AI-zoekhulp. Je kan mij alles vragen over boeken en events in de OBA. Bijvoorbeeld: 'boeken over prehistorische planteneters' of 'wat is er volgende week te doen in De Hallen?'";
    const messageContainer = document.getElementById('messages');
    const messageElement = document.createElement('div');
    messageElement.classList.add('assistant-message');
    messageElement.textContent = openingMessage;
    messageContainer.appendChild(messageElement);
    scrollToBottom();
}

function addPlaceholders() {
    const searchResultsContainer = document.getElementById('search-results');
    searchResultsContainer.innerHTML = `
        <div><img src="/static/images/placeholder.png" alt="Placeholder"></div>
        <div><img src="/static/images/placeholder.png" alt="Placeholder"></div>
        <div><img src="/static/images/placeholder.png" alt="Placeholder"></div>
        <div><img src="/static/images/placeholder.png" alt="Placeholder"></div>
    `;
}

function showErrorMessage() {
    displayAssistantMessage('er is iets misgegaan, we beginnen opnieuw');
    hideLoader();
    clearTimeout(timeoutHandle);
    resetThread();
    updateActionButtons();
    setTimeout(() => { clearErrorMessage(); }, 2000);
}

function clearErrorMessage() {
    const messageContainer = document.getElementById('messages');
    const lastMessage = messageContainer.lastChild;
    if (lastMessage && lastMessage.textContent.includes('er is iets misgegaan')) {
        messageContainer.removeChild(lastMessage);
    }
}

/* Init */
document.getElementById('user-input').addEventListener('input', function() {
    checkInput();
    if (this.value !== "") this.placeholder = "";
});
document.getElementById('user-input').addEventListener('keypress', function(event) {
    if (event.key === 'Enter') sendMessage();
});
document.querySelectorAll('#filters input[type="checkbox"]').forEach(checkbox => {
    checkbox.addEventListener('change', checkInput);
});

window.onload = async () => {
    await startThread();
    addOpeningMessage();
    addPlaceholders();
    checkInput();
    document.getElementById('user-input').placeholder = "Vertel me wat je zoekt!";
    const applyFiltersButton = document.querySelector('button[onclick="applyFiltersAndSend()"]');
    if (applyFiltersButton) applyFiltersButton.onclick = applyFiltersAndSend;
    resetFilters();
    linkedPPNs.clear();
    closeFilterPanel();
    closeResultPanel();
    if (!history.state) history.replaceState({ panel: 'chat' }, '', location.pathname);
    updateActionButtons();
};
