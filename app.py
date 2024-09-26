from flask import Flask, request, jsonify, render_template, url_for
import openai
import json
import requests
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')
openai_api_key = os.environ.get('OPENAI_API_KEY')
typesense_api_key = os.environ.get('TYPESENSE_API_KEY')
typesense_api_url = os.environ.get('TYPESENSE_API_URL')

openai.api_key = openai_api_key

assistant_id_1 = 'asst_ejPRaNkIhjPpNHDHCnoI5zKY'
assistant_id_2 = 'asst_mQ8PhYHrTbEvLjfH8bVXPisQ'
assistant_id_3 = 'asst_NLL8P78p9kUuiq08vzoRQ7tn'

def log_chat_to_google_sheets(user_input, assistant_response):
    try:
        url = 'https://script.google.com/macros/s/AKfycbxZHlNPRL-DtIMj3Q3_lVekJqE52Iy4iPAM36gvWIof2OdRJsPn9xbcD2y9iLADNI-_/exec'  
        payload = {
            'user_input': user_input,
            'assistant_response': assistant_response
        }
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"Failed to log chat: {response.text}")
    except Exception as e:
        print(f"Error logging chat to Google Sheets: {e}")

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
    except openai.error.OpenAIError as e:
        return str(e), thread_id
    except Exception as e:
        return str(e), thread_id

def extract_search_query(response):
    search_marker = "SEARCH_QUERY:"
    if search_marker in response:
        start_index = response.find(search_marker) + len(search_marker)
        search_query = response[start_index:].strip()
        return search_query
    return None

def extract_comparison_query(response):
    comparison_marker = "VERGELIJKINGS_QUERY:"
    if comparison_marker in response:
        start_index = response.find(comparison_marker) + len(comparison_marker)
        comparison_query = response[start_index:].strip()
        return comparison_query
    return None

def parse_assistant_message(content):
    try:
        parsed_content = json.loads(content)
        return {
            "q": parsed_content.get("q", ""),
            "query_by": parsed_content.get("query_by", ""),
            "collection": parsed_content.get("collection", ""),
            "vector_query": parsed_content.get("vector_query", ""),
            "filter_by": parsed_content.get("filter_by", "")
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
            "include_fields": "titel,ppn",
            "per_page": 15,
            "filter_by": params["filter_by"]
        }]
    }

    response = requests.post(typesense_api_url, headers=headers, json=body)
    
    if response.status_code == 200:
        search_results = response.json()
        results = [
            {
                "ppn": hit["document"]["ppn"],
                "titel": hit["document"]["titel"]
            } for hit in search_results["results"][0]["hits"]
        ]

        simplified_results = {"results": results}
        return simplified_results
    else:
        return {"error": response.status_code, "message": response.text}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_thread', methods=['POST'])
def start_thread():
    try:
        thread = openai.beta.threads.create()
        return jsonify({'thread_id': thread.id})
    except openai.error.OpenAIError as e:
        return jsonify({'error': str(e)}), 500
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

        if search_query:
            response_text_2, thread_id = call_assistant(assistant_id_2, search_query, thread_id)
            search_params = parse_assistant_message(response_text_2)
            if search_params:
                search_results = perform_typesense_search(search_params)
                return jsonify({'response': search_results, 'thread_id': thread_id})
            else:
                return jsonify({'response': response_text_2, 'thread_id': thread_id})
        elif comparison_query:
            response_text_3, thread_id = call_assistant(assistant_id_3, comparison_query, thread_id)
            search_params = parse_assistant_message(response_text_3)
            if search_params:
                search_results = perform_typesense_search(search_params)
                return jsonify({'response': search_results, 'thread_id': thread_id})
            else:
                return jsonify({'response': response_text_3, 'thread_id': thread_id})
        else:
            return jsonify({'response': response_text, 'thread_id': thread_id})
    except openai.error.OpenAIError as e:
        return jsonify({'error': str(e)}), 500
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
                search_results = perform_typesense_search(search_params)
                return jsonify({'results': search_results['results'], 'thread_id': thread_id})
            else:
                return jsonify({'response': response_text_2, 'thread_id': thread_id})
        elif comparison_query:
            response_text_3, thread_id = call_assistant(assistant_id_3, comparison_query, thread_id)
            search_params = parse_assistant_message(response_text_3)
            if search_params:
                search_results = perform_typesense_search(search_params)
                return jsonify({'results': search_results['results'], 'thread_id': thread_id})
            else:
                return jsonify({'response': response_text_3, 'thread_id': thread_id})
        else:
            return jsonify({'response': response_text, 'thread_id': thread_id})
    except openai.error.OpenAIError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/reset', methods=['POST'])
def reset():
    return jsonify({'status': 'reset'})

@app.route('/proxy/resolver', methods=['GET'])
def proxy_resolver():
    ppn = request.args.get('ppn')
    url = f'https://zoeken.oba.nl/api/v1/resolver/ppn/?id={ppn}&authorization=ffbc1ededa6f23371bc40df1864843be'
    response = requests.get(url)
    return response.content, response.status_code, response.headers.items()

@app.route('/proxy/details', methods=['GET'])
def proxy_details():
    item_id = request.args.get('item_id')
    url = f'https://zoeken.oba.nl/api/v1/details/?id=|oba-catalogus|{item_id}&authorization=ffbc1ededa6f23371bc40df1864843be&output=json'
    response = requests.get(url)
    
    if response.headers['Content-Type'] == 'application/json':
        return jsonify(response.json()), response.status_code, response.headers.items()
    else:
        return response.text, response.status_code, response.headers.items()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
