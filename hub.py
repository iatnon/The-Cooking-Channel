from flask import Flask, request, render_template, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
import json
import datetime
import requests

db = SQLAlchemy()

class Channel(db.Model):
    __tablename__ = 'channels'
    id = db.Column(db.Integer, primary_key=True)
    active = db.Column('is_active', db.Boolean(), nullable=False, server_default='1')
    name = db.Column(db.String(100, collation='NOCASE'), nullable=False)
    endpoint = db.Column(db.String(100, collation='NOCASE'), nullable=False, unique=True)
    authkey = db.Column(db.String(100, collation='NOCASE'), nullable=False)
    type_of_service = db.Column(db.String(100, collation='NOCASE'), nullable=False)
    last_heartbeat = db.Column(db.DateTime(), nullable=True, server_default=None)


# Class-based application configuration
class ConfigClass(object):
    """ Flask application config """

    # Flask settings
    SECRET_KEY = 'This is an INSECURE secret!! DO NOT use this in production!!'

    # Flask-SQLAlchemy settings
    SQLALCHEMY_DATABASE_URI = 'sqlite:///chat_server.sqlite'  # File-based SQL database
    SQLALCHEMY_TRACK_MODIFICATIONS = False  # Avoids SQLAlchemy warning

# Create Flask app
app = Flask(__name__)
app.config.from_object(__name__ + '.ConfigClass')  # configuration
app.app_context().push()  # create an app context before initializing db
db.init_app(app)  # initialize database
db.create_all()  # create database if necessary

SERVER_AUTHKEY = '1234567890'
STANDARD_CLIENT_URL = 'http://localhost:5005' # standard configuration in client.py, chang to real URL if necessary

def health_check(endpoint, authkey):
    # make GET request to URL
    # add authkey to request header
    try:
        response = requests.get(endpoint+'/health',
                                headers={'Authorization': 'authkey '+authkey})
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return False
    if response.status_code != 200:
        return False
    # check if response is JSON with {"name": <channel_name>}
    if 'name' not in response.json():
        return False
    # check if channel name is as expected
    # (channels can't change their name, must be re-registered)
    channel = Channel.query.filter_by(endpoint=endpoint).first()
    channel.active = False
    db.session.commit()
    if not channel:
        print(f"Channel {endpoint} not found in database")
        return False
    expected_name = channel.name
    if response.json()['name'] != expected_name:
        return False

    # everything is OK, set last_heartbeat to now
    channel.active = True
    channel.last_heartbeat = datetime.datetime.now()
    db.session.commit()  # save to database
    return True

# cli command to check health of all channels
@app.cli.command('check_channels')
def check_channels():
    channels = Channel.query.all()
    for channel in channels:
        if not health_check(channel.endpoint, channel.authkey):
            print(f"Channel {channel.endpoint} is not healthy")
        else:
            print(f"Channel {channel.endpoint} is healthy")

# The Home page is accessible to anyone
@app.route('/')
def home_page():
    # find all active channels
    channels = Channel.query.filter_by(active=True).all()
    # render hub_home.html template
    return render_template("hub_home.html", channels=channels, STANDARD_CLIENT_URL=STANDARD_CLIENT_URL)


# Flask REST route for POST to /channels
@app.route('/channels', methods=['POST'])
def create_channel():
    global SERVER_AUTHKEY

    record = json.loads(request.data)

    # check if authorization header is present
    if 'Authorization' not in request.headers:
        return "No authorization header", 400
    # check if authorization header is valid
    if request.headers['Authorization'] != 'authkey ' + SERVER_AUTHKEY:
        return "Invalid authorization header ({})".format(request.headers['Authorization']), 400
    if 'name' not in record:
        return "Record has no name", 400
    if 'endpoint' not in record:
        return "Record has no endpoint", 400
    if 'authkey' not in record:
        return "Record has no authkey", 400
    if 'type_of_service' not in record:
        return "Record has no type of service representation", 400

    update_channel = Channel.query.filter_by(endpoint=record['endpoint']).first()
    print("update_channel: ", update_channel)
    if update_channel:  # Channel already exists, update it
        update_channel.name = record['name']
        update_channel.authkey = record['authkey']
        update_channel.type_of_service = record['type_of_service']
        update_channel.active = False
        db.session.commit()
        if not health_check(record['endpoint'], record['authkey']):
            return "Channel is not healthy", 400
        return jsonify(created=False,
                       id=update_channel.id), 200
    else:  # new channel, create it
        channel = Channel(name=record['name'],
                          endpoint=record['endpoint'],
                          authkey=record['authkey'],
                          type_of_service=record['type_of_service'],
                          last_heartbeat=datetime.datetime.now(),
                          active=True)
        db.session.add(channel)
        db.session.commit()
        if not health_check(record['endpoint'], record['authkey']):
            # delete channel from database
            db.session.delete(channel)
            db.session.commit()
            return "Channel is not healthy", 400

        return jsonify(created=True, id=channel.id), 200


@app.route('/channels', methods=['GET'])
def get_channels():
    channels = Channel.query.filter_by(active=True).all()

    return jsonify(channels=[{'name': c.name,
                              'endpoint': c.endpoint,
                              'authkey': c.authkey,
                              'type_of_service': c.type_of_service} for c in channels]), 200


@app.route('/health', methods=['GET'])
def health():
    # check either all channels or a specific channel (if id is provided)
    if 'id' in request.args:
        channel = Channel.query.filter_by(id=request.args['id']).first()
        health_check(channel.endpoint, channel.authkey)
    else:
        channels = Channel.query.all()
        for channel in channels:
            health_check(channel.endpoint, channel.authkey)

    # flask redirect to home page
    return redirect(url_for('home_page'))



# Start development web server
if __name__ == '__main__':
    app.run(port=5555, debug=True)
