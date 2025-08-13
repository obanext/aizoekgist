from flask import Flask, request, jsonify, render_template, url_for
import openai
import json
import requests
import os
import xml.etree.ElementTree as ET
from datetime import datetime

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
        response = requests.get(api_url)
        response.raise_for_status()
        root = ET.fromstring(response.text)

        results = []
        result_nodes = root.find('results')
        if result_nodes is None:
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
                "raw_date": {
                    "start": raw_start,
                    "end": raw_end
                }
            })

        return results
    except Exception:
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
        else:
            openai.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=user_input
            )
        event_handler = CustomEventHandler()
        with openai.beta.threads.runs.stream(
            thread_id=thread_id,
            assistant_id=assistant_id,
            event_handler=event_handler,
        ) as stream:
            stream.until_done()
        return event_handler.response_text, thread_id
    except Exception as e:
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
        return None

def perform_typesense_search(params):
    headers = {
        'Content-Type': 'application/json',
        'X-TYPESENSE-API-KEY': typesense_api_key,
    }
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
    response = requests.post(typesense_api_url, headers=headers, json=body)
    if response.status_code == 200:
        hits = response.json()["results"][0]["hits"]
        return {"results": [{"ppn": h["document"]["ppn"], "short_title": h["document"]["short_title"]} for h in hits]}
    else:
        return {"error": response.status_code, "message": response.text}

def perform_typesense_search_events(params):
    headers = {
        'Content-Type': 'application/json',
        'X-TYPESENSE-API-KEY': typesense_api_key,
    }
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
    response = requests.post(typesense_api_url, headers=headers, json=body)
    if response.status_code == 200:
        hits = response.json()["results"][0]["hits"]
        return [h["document"]["nativeid"] for h in hits if "nativeid" in h["document"]]
    else:
        return []

def fetch_event_detail(nativeid):
    try:
        url = f'https://zoeken.oba.nl/api/v1/details/?id=|evenementen|{nativeid}&authorization={oba_api_key}&output=json'
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()

        record = data.get("record", {})

        title = (record.get("titles") or ["Geen titel"])[0] if isinstance(record.get("titles"), list) else record.get("titles", "Geen titel")
        summary = (record.get("summaries") or [""])[0] if isinstance(record.get("summaries"), list) else record.get("summaries", "")
        cover = (record.get("coverimages") or [""])[0] if isinstance(record.get("coverimages"), list) else record.get("coverimages", "")

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

        return {
            "title": title or "Geen titel",
            "cover": cover or "",
            "link": detail_link or "#",
            "summary": summary or "",
            "date": date_str,
            "time": time_str,
            "location": location,
            "raw_date": {
                "start": raw_start,
                "end": raw_end
            }
        }
    except Exception:
        return None

def build_agenda_results_from_nativeids(nativeids):
    results = []
    for nid in nativeids:
        detail = fetch_event_detail(nid)
        if detail:
            results.append(detail)
    return results

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_thread', methods=['POST'])
def start_thread():
    try:
        thread = openai.beta.threads.create()
        return jsonify({'thread_id': thread.id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/send_message', methods=['POST'])
def send_message():
    try:
        data = request.json
        thread_id = data['thread_id']
        user_input = data['user_input']
        assistant_id = data['assistant_id']

        response_text, thread_id = call_assistant(assistant_id, user_input, thread_id)
        search_query = extract_search_query(response_text)
        comparison_query = extract_comparison_query(response_text)
        agenda_query = extract_agenda_query(response_text)

        if search_query:
            response_text_2, thread_id = call_assistant(assistant_id_2, search_query, thread_id)
            search_params = parse_assistant_message(response_text_2)
            if search_params:
                if search_params.get("collection") == "obadb30725events":
                    nativeids = perform_typesense_search_events(search_params)
                    agenda_results = build_agenda_results_from_nativeids(nativeids)
                    first_url = agenda_results[0]["link"] if agenda_results else ""
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
            if search_params:
                if search_params.get("collection") == "obadb30725events":
                    nativeids = perform_typesense_search_events(search_params)
                    agenda_results = build_agenda_results_from_nativeids(nativeids)
                    first_url = agenda_results[0]["link"] if agenda_results else ""
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
                return jsonify({'response': response_text_4, 'thread_id': thread_id})
            results = fetch_agenda_results(agenda_obj["API"])
            return jsonify({
                'response': {
                    'type': 'agenda',
                    'url': agenda_obj["URL"],
                    'message': agenda_obj["Message"],
                    'results': results
                },
                'thread_id': thread_id
            })

        return jsonify({'response': response_text, 'thread_id': thread_id})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/apply_filters', methods=['POST'])
def apply_filters():
    try:
        data = request.json
        thread_id = data['thread_id']
        filter_values = data['filter_values']
        assistant_id = data['assistant_id']

        response_text, thread_id = call_assistant(assistant_id, filter_values, thread_id)
        search_query = extract_search_query(response_text)
        comparison_query = extract_comparison_query(response_text)

        if search_query:
            response_text_2, thread_id = call_assistant(assistant_id_2, search_query, thread_id)
            search_params = parse_assistant_message(response_text_2)
            if search_params:
                if search_params.get("collection") == "obadb30725events":
                    nativeids = perform_typesense_search_events(search_params)
                    agenda_results = build_agenda_results_from_nativeids(nativeids)
                    return jsonify({'response': {'type': 'agenda', 'url': (agenda_results[0]["link"] if agenda_results else ""), 'message': "Is dit wat je zoekt of ben je op zoek naar iets anders?", 'results': agenda_results}, 'thread_id': thread_id})
                results = perform_typesense_search(search_params)
                return jsonify({'results': results['results'], 'thread_id': thread_id})
            return jsonify({'response': response_text_2, 'thread_id': thread_id})

        elif comparison_query:
            response_text_3, thread_id = call_assistant(assistant_id_3, comparison_query, thread_id)
            search_params = parse_assistant_message(response_text_3)
            if search_params:
                if search_params.get("collection") == "obadb30725events":
                    nativeids = perform_typesense_search_events(search_params)
                    agenda_results = build_agenda_results_from_nativeids(nativeids)
                    return jsonify({'response': {'type': 'agenda', 'url': (agenda_results[0]["link"] if agenda_results else ""), 'message': "Is dit wat je zoekt of ben je op zoek naar iets anders?", 'results': agenda_results}, 'thread_id': thread_id})
                results = perform_typesense_search(search_params)
                return jsonify({'results': results['results'], 'thread_id': thread_id})
            return jsonify({'response': response_text_3, 'thread_id': thread_id})

        return jsonify({'response': response_text, 'thread_id': thread_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/proxy/resolver', methods=['GET'])
def proxy_resolver():
    ppn = request.args.get('ppn')
    url = f'https://zoeken.oba.nl/api/v1/resolver/ppn/?id={ppn}&authorization={oba_api_key}'
    response = requests.get(url)
    return response.content, response.status_code, response.headers.items()

@app.route('/proxy/details', methods=['GET'])
def proxy_details():
    item_id = request.args.get('item_id')
    url = f'https://zoeken.oba.nl/api/v1/details/?id=|oba-catalogus|{item_id}&authorization={oba_api_key}&output=json'
    response = requests.get(url)
    if response.headers.get('Content-Type') == 'application/json':
        return jsonify(response.json()), response.status_code, response.headers.items()
    return response.text, response.status_code, response.headers.items()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
