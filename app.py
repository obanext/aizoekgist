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

human_handover_active = False

def detect_human_handover_trigger(user_input):
    return "paprika" in user_input.lower()

def notify_human_agent(thread_id):
    print(f"Notificatie gestuurd naar menselijke agent voor thread_id: {thread_id}")

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
        if response.status_code != 200:
            print(f"Failed to log chat: {response.text}")
    except Exception as e:
        print(f"Error logging chat to Google Sheets: {e}")

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

@app.route('/send_message', methods=['POST'])
def send_message():
    global human_handover_active
    try:
        data = request.json
        thread_id = data['thread_id']
        user_input = data['user_input']
        assistant_id = data['assistant_id']

        if detect_human_handover_trigger(user_input):
            human_handover_active = True
            notify_human_agent(thread_id)
            return jsonify({'response': "Ik zoek er een mens bij", 'thread_id': thread_id})

        if human_handover_active:
            return jsonify({'response': "Menselijke agent actief, OpenAI gepauzeerd", 'thread_id': thread_id})

        response_text, thread_id = call_assistant(assistant_id, user_input, thread_id)
        log_chat_to_google_sheets(user_input, response_text, thread_id)
        return jsonify({'response': response_text, 'thread_id': thread_id})

    except openai.error.OpenAIError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/human_send_message', methods=['POST'])
def human_send_message():
    global human_handover_active
    try:
        data = request.json
        user_message = data['message']
        thread_id = data['thread_id']
        print(f"Menselijke agent stuurt bericht: {user_message}")
        return jsonify({'response': f"Agent: {user_message}", 'thread_id': thread_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/return_to_openai', methods=['POST'])
def return_to_openai():
    global human_handover_active
    try:
        data = request.json
        thread_id = data['thread_id']
        human_handover_active = False
        return jsonify({'response': "Controle teruggegeven aan OpenAI", 'thread_id': thread_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/handover_to_human', methods=['POST'])
def handover_to_human():
    global human_handover_active
    try:
        data = request.json
        thread_id = data['thread_id']
        notify_human_agent(thread_id)
        return jsonify({'response': "Menselijke agent ingeschakeld", 'thread_id': thread_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
