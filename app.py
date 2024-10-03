
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
