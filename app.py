from flask import Flask, request, jsonify, render_template, url_for
import openai
import json
import requests
import os
import threading

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')
openai_api_key = os.environ.get('OPENAI_API_KEY')
typesense_api_key = os.environ.get('TYPESENSE_API_KEY')
typesense_api_url = os.environ.get('TYPESENSE_API_URL')

openai.api_key = openai_api_key

assistant_id_1 = 'asst_ejPRaNkIhjPpNHDHCnoI5zKY'
assistant_id_2 = 'asst_mQ8PhYHrTbEvLjfH8bVXPisQ'
assistant_id_3 = 'asst_NLL8P78p9kUuiq08vzoRQ7tn'

# Om bij te houden welke threads een menselijke agent nodig hebben
thread_handover_status = {}
ongoing_human_interventions = {}
lock = threading.Lock()

def log_chat_to_google_sheets(user_input, assistant_response, thread_id):
    try:
        url = 'https://script.google.com/macros/s/AKfycbxqMBJMmdgSu-VPvJM9LtKKFpId6KLRLgddrhnNk_yC3RkF0vJMTn4hNhRw4v3a6vGY/exec'
        payload = {
            'thread_id': thread_id,  
            'user_input': user_input,
            'assistant_response': assistant_response
        }
        headers = {
            'Content-Type': 'application/json'
        }
        response = requests.post(url, json=payload, headers=headers)
    except Exception as e:
        pass

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

# Assistent call functie
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

# Zoeklogica voor Typesense
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

        return {"results": results}
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

        # Controleer op "paprika" voor handover
        if 'paprika' in user_input.lower():
            with lock:
                thread_handover_status[thread_id] = True
            return jsonify({'response': 'Handover gestart, een menselijke agent neemt het gesprek over.', 'thread_id': thread_id})

        # Als er een menselijke interventie is, stuur het bericht naar de agent
        if thread_id in ongoing_human_interventions:
            return jsonify({'response': f"Menselijke agent: {user_input}", 'thread_id': thread_id})

        # Normale assistent call
        response_text, thread_id = call_assistant(assistant_id, user_input, thread_id)
        log_chat_to_google_sheets(user_input, response_text, thread_id)

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
        if search_query:
            search_results = perform_typesense_search(search_query)
            return jsonify({'results': search_results['results'], 'thread_id': thread_id})
        else:
            return jsonify({'response': response_text, 'thread_id': thread_id})
    except openai.error.OpenAIError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/request_handover', methods=['POST'])
def request_handover():
    try:
        data = request.get_json()
        thread_id = data.get('thread_id')

        if 'paprika' in data.get('message', '').lower():
            with lock:
                thread_handover_status[thread_id] = True
            return jsonify({'handover': 'success'})
        else:
            return jsonify({'handover': 'failed'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/handover_list', methods=['GET'])
def handover_list():
    handover_threads = [thread_id for thread_id, handover in thread_handover_status.items() if handover]
    return jsonify({'handover_threads': handover_threads})

@app.route('/send_agent_message', methods=['POST'])
def send_agent_message():
    try:
        data = request.json
        thread_id = data.get('thread_id')
        agent_message = data.get('message')

        openai.beta.threads.messages.create(
            thread_id=thread_id,
            role="agent",
            content=agent_message
        )
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/agent_join_thread/<thread_id>', methods=['POST'])
def agent_join_thread(thread_id):
    try:
        openai.beta.threads.messages.create(
            thread_id=thread_id,
            role="agent",
            content="Hoi OBA mens hier! Waarmee kan ik je helpen?"
        )
        with lock:
            ongoing_human_interventions[thread_id] = True
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
