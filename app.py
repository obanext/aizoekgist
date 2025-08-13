from flask import Flask, request, jsonify, render_template, url_for, g
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

openai_api_key = os.environ.get('OPENAI_API_KEY')
typesense_api_key = os.environ.get('TYPESENSE_API_KEY')
typesense_api_url = os.environ.get('TYPESENSE_API_URL')
oba_api_key = os.environ.get('OBA_API_KEY')
openai.api_key = openai_api_key

assistant_id_1 = 'asst_ejPRaNkIhjPpNHDHCnoI5zKY'
assistant_id_2 = 'asst_iN7gutrYjI18E97U42GODe4B'
assistant_id_3 = 'asst_NLL8P78p9kUuiq08vzoRQ7tn'
assistant_id_4 = 'asst_9Adxq0d95aUQbMfEGtqJLVx1'

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

def extract_search_query(response):
    marker = "SEARCH_QUERY:"
    if marker in response:
        return response.split(marker, 1)[1].strip()
    return None

def extract_comparison_query(response):
    marker = "VERGELIJKINGS_QUERY:"
    if marker in response:
        return response.split(marker, 1)[1].strip()
    return None

def extract_agenda_query(response):
    marker = "AGENDA_VRAAG:"
    if marker in response:
        return response.split(marker, 1)[1].strip()
    return None

def fetch_agenda_results(api_url):
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
            link = result.findtext('.//detail-page') or "#"
            summary = result.findtext('.//summaries/summary') or ""
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
    except Exception as e:
        logger.exception("agenda_xml_error")
        return []

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
    except Exception as e:
        logger.exception("openai_error")
        return str(e), thread_id

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
        nativeids = [h["document"]["nativeid"] for h in hits if "nativeid" in h["document"]]
        logger.info(f"typesense_events_hits count={len(hits)} nativeids={len(nativeids)}")
        return nativeids
    else:
        logger.warning(f"typesense_events_error status={response.status_code}")
        return []

def fetch_event_detail(nativeid):
    try:
        url = f'https://zoeken.oba.nl/api/v1/details/?id=|evenementen|{nativeid}&authorization={oba_api_key}&output=json'
        logger.info(f"event_detail_fetch nativeid={nativeid} url={url}")
        r = requests.get(url, timeout=15)
        logger.info(f"event_detail_response nativeid={nativeid} status={r.status_code}")
        if r.status_code != 200:
            return None
        data = r.json()
        record = data.get("record", {})
        titles = record.get("titles") or []
        summaries = record.get("summaries") or []
        coverimages = record.get("coverimages") or []
        title = titles[0] if isinstance(titles, list) and titles else record.get("titles", "Geen titel")
        summary = summaries[0] if isinstance(summaries, list) and summaries else record.get("summaries", "")
        cover = coverimages[0] if isinstance(coverimages, list) and coverimages else record.get("coverimages", "")
        detail_link = record.get("detail-page") or "#"
        custom = record.get("custom", {})
        gebeurtenis = custom.get("gebeurtenis", {}) if isinstance(custom, dict) else {}
        datum = gebeurtenis.get("datum", {}) if isinstance(gebeurtenis, dict) else {}
        gebouw = gebeurtenis.get("gebouw", "") if isinstance(gebeurtenis, dict) else ""
        locatienaam = gebeurtenis.get("locatienaam", "") if isinstance(gebeurtenis, dict) else ""
        raw_start = datum.get("start", "") if isinstance(datum, dict) else ""
        raw_end = datum.get("eind", "") if isinstance(datum, dict) else ""
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
        has_title = bool(title)
        logger.info(f"event_detail_parsed nativeid={nativeid} has_title={has_title}")
        return {
            "title": title or "Geen titel",
            "cover": cover or "",
            "link": detail_link or "#",
            "summary": summary or "",
            "date": date_str,
            "time": time_str,
            "location": location,
            "raw_date": {"start": raw_start, "end": raw_end}
        }
    except Exception:
        logger.exception(f"event_detail_error nativeid={nativeid}")
        return None

def build_agenda_results_from_nativeids(nativeids):
    results = []
    for nid in nativeids:
        detail = fetch_event_detail(nid)
        if detail:
            results.append(detail)
    logger.info(f"agenda_build_from_nativeids count_in={len(nativeids)} count_out={len(results)}")
    return results

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
                if coll == "obadb30725events":
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
                if coll == "obadb30725events":
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

            if "q" in agenda_obj and "collection" in agenda_obj:
                logger.info("agenda_path=B")
                params = {
                    "q": agenda_obj.get("q", ""),
                    "collection": agenda_obj.get("collection", ""),
                    "query_by": agenda_obj.get("query_by", "embedding"),
                    "vector_query": agenda_obj.get("vector_query", "embedding:([], alpha: 0.8)"),
                    "filter_by": agenda_obj.get("filter_by", "")
                }
                if params["collection"] == "obadb30725events":
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
                if coll == "obadb30725events":
                    nativeids = perform_typesense_search_events(search_params)
                    agenda_results = build_agenda_results_from_nativeids(nativeids)
                    logger.info(f"agenda_results_count={len(agenda_results)}")
                    return jsonify({'response': {'type': 'agenda', 'url': (agenda_results[0]["link"] if agenda_results else ""), 'message': "Is dit wat je zoekt of ben je op zoek naar iets anders?", 'results': agenda_results}, 'thread_id': thread_id})
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
                if coll == "obadb30725events":
                    nativeids = perform_typesense_search_events(search_params)
                    agenda_results = build_agenda_results_from_nativeids(nativeids)
                    logger.info(f"agenda_results_count={len(agenda_results)}")
                    return jsonify({'response': {'type': 'agenda', 'url': (agenda_results[0]["link"] if agenda_results else ""), 'message': "Is dit wat je zoekt of ben je op zoek naar iets anders?", 'results': agenda_results}, 'thread_id': thread_id})
                results = perform_typesense_search(search_params)
                return jsonify({'results': results.get('results', []), 'thread_id': thread_id})
            return jsonify({'response': response_text_3, 'thread_id': thread_id})
        logger.info("apply_filters_fallback_text")
        return jsonify({'response': response_text, 'thread_id': thread_id})
    except Exception as e:
        logger.exception("apply_filters_error")
        return jsonify({'error': str(e)}), 500

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
    if response.headers.get('Content-Type') == 'application/json':
        return jsonify(response.json()), response.status_code, response.headers.items()
    return response.text, response.status_code, response.headers.items()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
