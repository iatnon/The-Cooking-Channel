## channel.py - a simple message channel
##
import re
from flask import Flask, request, render_template, jsonify
import json
import requests

# Class-based application configuration
class ConfigClass(object):
    """ Flask application config """

    # Flask settings
    SECRET_KEY = 'This is an INSECURE secret!! DO NOT use this in production!!' # change to something random, no matter what

# Create Flask app
app = Flask(__name__)
app.config.from_object(__name__ + '.ConfigClass')  # configuration
app.app_context().push()  # create an app context before initializing db

HUB_URL = 'http://localhost:5555'
HUB_AUTHKEY = '1234567890'
SERVER_AUTHKEY = 'Crr-K24d-2N'
CHANNEL_NAME = "The Cooking Channel"
CHANNEL_ENDPOINT = "http://localhost:5001" # don't forget to adjust in the bottom of the file
CHANNEL_FILE = 'messages.json'
CHANNEL_TYPE_OF_SERVICE = 'aiweb24:chat'
PROMPT = """You are a helpful manager and assistant of a cooking channel. You can help the user with any cooking related question. When a user provides a recipe always provide an esimate of the main 8 nutritional facts, also provide suggestions or tips that can help the user. 
If the user request anything that is not related to cooking or includes any harmful content, please inform the user that this channel is not targeted towards the requested content, provide the user with an answer as to why the exact request is not allowed.
Strictuly respond in json format with the following structure:
in case of a valid response {
    "response": "Here are some tips for the recipe you provided...",
    "allowed": true,
}
in case of an invalid response {
    "response": "This channel is not targeted towards the requested content...",
    "allowed": false,
}.
This is the users requesst:
"""

def extract_json_from_markdown(response: str) -> str:
    # Look for ```json ... ```
    match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
    if match:
        return match.group(1)
    else:
        # If no markdown block is found, assume the entire response is JSON
        return response.strip()
    
def parse_llm_response(llm_response: str):
    # Extract JSON content
    json_content = extract_json_from_markdown(llm_response)
    
    # Attempt to parse the JSON
    try:
        parsed_data = json.loads(json_content)
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON: {e}")
        print(f"Invalid JSON content: {json_content}")
        return None
    
    # Ensure the parsed data is a list (assuming that's the expected structure)
    if not isinstance(parsed_data, dict):
        print(f"Expected a list, got: {type(parsed_data)}")
        return None
    
    return parsed_data

def chat(conversation_history):
    history = []
    for conversation in conversation_history:
        if 'user' in conversation:
            history.append({
                'role': 'user',
                'text': conversation['user'],
                'images': conversation.get('images')  # Use .get() to avoid errors if 'images' is missing
            })
        if 'model' in conversation:
            history.append({'role': 'model', 'text': conversation['model']})

    body = json.dumps({
        'conversation_history': history,
    })

    url = 'https://vertex-backend-607079336624.europe-west4.run.app/chat'
    headers = {
        'Content-Type': 'application/json',
    }

    try:
        response = requests.post(url, headers=headers, data=body)
        if response.status_code == 200:
            response_data = response.json()
            original_string = response_data.get('response', '')
            result = parse_llm_response(original_string)
  
            return result
        else:
            print(f'Failed with status code: {response.status_code}')
            print(f'Response body: {response.text}')
            return None
    except Exception as e:
        print(f'Error: {e}')
        return None

@app.cli.command('register')
def register_command():
    global CHANNEL_AUTHKEY, CHANNEL_NAME, CHANNEL_ENDPOINT

    # send a POST request to server /channels
    response = requests.post(HUB_URL + '/channels', headers={'Authorization': 'authkey ' + HUB_AUTHKEY},
                             data=json.dumps({
                                "name": CHANNEL_NAME,
                                "endpoint": CHANNEL_ENDPOINT,
                                "authkey": CHANNEL_AUTHKEY,
                                "type_of_service": CHANNEL_TYPE_OF_SERVICE,
                             }))

    if response.status_code != 200:
        print("Error creating channel: "+str(response.status_code))
        print(response.text)
        return

def check_authorization(request):
    global CHANNEL_AUTHKEY
    # check if Authorization header is present
    if 'Authorization' not in request.headers:
        return False
    # check if authorization header is valid
    if request.headers['Authorization'] != 'authkey ' + CHANNEL_AUTHKEY:
        return False
    return True

@app.route('/health', methods=['GET'])
def health_check():
    global CHANNEL_NAME
    if not check_authorization(request):
        return "Invalid authorization", 400
    return jsonify({'name':CHANNEL_NAME}),  200

# GET: Return list of messages
@app.route('/', methods=['GET'])
def home_page():
    if not check_authorization(request):
        return "Invalid authorization", 400
    # fetch channels from server
    return jsonify(read_messages())

# POST: Send a message
@app.route('/', methods=['POST'])
def send_message():
    # fetch channels from server
    # check authorization header
    if not check_authorization(request):
        return "Invalid authorization", 400
    # check if message is present
    message = request.json
    if not message:
        return "No message", 400
    if not 'content' in message:
        return "No content", 400
    if not 'sender' in message:
        return "No sender", 400
    if not 'timestamp' in message:
        return "No timestamp", 400
    if not 'extra' in message:
        extra = None
    else:
        extra = message['extra']
    # add message to messages
    messages = read_messages()
    if len(messages) > 3:
        messages.pop(0)
    
    llm_result = chat([{'user': f"{PROMPT} {message['content']} the name of the user is {message['sender']}, address him/her nicely", 'images': []}])
    allowed = llm_result.get('allowed', True)
    if isinstance(allowed, str):
        if allowed == allowed.lower() == 'false':
            allowed = False
        else:
            allowed = True

    response = llm_result.get('response', 'Error: No response')
    if allowed:
        messages.append({'content': message['content'],
                        'sender': message['sender'],
                        'timestamp': message['timestamp'],
                        'extra': extra,
                        })
    messages.append({'content': response,
                     'sender': 'Server',
                     'timestamp': message['timestamp'],
                     'extra': extra,
                     })
    # messages.append({'content': f'You just send this message: {message['content']}',
    #                  'sender': 'server',
    #                  'timestamp': message['timestamp'],
    #                  'extra': extra,
    #                  })
    save_messages(messages)
    return "OK", 200

def read_messages():
    global CHANNEL_FILE
    try:
        f = open(CHANNEL_FILE, 'r')
    except FileNotFoundError:
        return []
    try:
        messages = json.load(f)
    except json.decoder.JSONDecodeError:
        messages = []
    f.close()
    return messages

def save_messages(messages):
    global CHANNEL_FILE
    with open(CHANNEL_FILE, 'w') as f:
        json.dump(messages, f)

# Start development web server
# run flask --app channel.py register
# to register channel with hub

if __name__ == '__main__':
    app.run(port=5001, debug=True)
