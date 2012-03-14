from datetime import datetime
import json
import os

import urlparse

import requests

from flask import Flask, request, redirect, abort
from flaskext.sqlalchemy import SQLAlchemy

app = Flask(__name__)
db_url = os.environ.get('DATABASE_URL', 'sqlite:////tmp/test.db')
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
db = SQLAlchemy(app)

OAUTH_CLIENT = os.environ.get('OAUTH_CLIENT', '')
OAUTH_SECRET = os.environ.get('OAUTH_SECRET', '')


class Model(object):

    def __init__(self, **kw):
        for key, value in kw.items():
            setattr(self, key, value)


class User(Model, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created = db.Column(db.DateTime, default=datetime.now)
    username = db.Column(db.String(80), unique=True)
    # The OAuth token.
    access_token = db.Column(db.String(256), nullable=True)
    # The blob of user data from the API.
    api_data = db.Column(db.Text, nullable=True)
    # The push notification URL.
    push_url = db.Column(db.String(256), nullable=True)


class Subscription(Model, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # username/repo-name
    repo = db.Column(db.String(256))
    created = db.Column(db.DateTime, default=datetime.now)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship('User',
                           backref=db.backref('subscriptions', lazy='dynamic'))


@app.route('/', methods=['GET'])
def root():
    return open('index.html').read()


@app.route('/queue', methods=['POST'])
def add_queue():
    queue = request.form['queue']
    token = request.form['access_token']
    user = User.query.filter_by(access_token=token).first_or_404()
    user.push_url = queue
    db.session.add(user)
    db.session.commit()
    notify(queue, 'Welcome to Github Notifications!',
           'So glad to have you %s.' % user.username)
    return ''


@app.route('/oauth', methods=['GET'])
def oauth():
    if 'code' in request.args:
        code = request.args['code']
        r = requests.post('https://github.com/login/oauth/access_token',
                          {'code': code,
                           'client_id': OAUTH_CLIENT,
                           'client_secret': OAUTH_SECRET})
        token = dict(urlparse.parse_qsl(r.text))['access_token']

        r = requests.get('https://api.github.com/user?access_token=%s' % token)
        data = json.loads(r.text)
        user = User.query.filter_by(username=data['login']).first()
        if user:
            user.access_token = token
            user.api_data = r.text
        else:
            user = User(username=data['login'],
                        access_token=token,
                        api_data=r.text)
        db.session.add(user)
        db.session.commit()

        response = redirect('/')
        response.set_cookie('access_token', token)
        response.set_cookie('username', user.username)
        return response

    return redirect('/')


@app.route('/hook', methods=['POST'])
def hook():
    payload = json.loads(request.form['payload'])
    import pprint; pprint.pprint(payload)
    repo = payload['repository']
    commit = payload['commits'][0]

    title = '%s - %s' % (repo['name'], commit['author']['name'])
    body = commit['message']
    action = commit['url']
    if len(payload['commits']) == 1:
        body += ' (and %s more)' % len(payload['commits'])
        before, after = payload['before'][:8], payload['after'][:8]
        action = '%s/compare/%s...%s' % (repo['url'], before, after)

    repo_slug = normalize(repo['url'])
    q = User.query.join(User.subscriptions).filter(Subscription.repo == repo_slug)
    for user in q.all():
        if user.push_url:
            notify(user.push_url, title, body)
    return ''


def normalize(repo_url):
    return '/'.join(repo_url.split('/')[-2:])


@app.route('/subscribe', methods=['POST'])
def subscribe():
    repo = request.form['repo']
    token = request.form['access_token']

    user = User.query.filter_by(access_token=token).first_or_404()
    if token == user.access_token:
        r = requests.get(repo + '/collaborators/%s' % user.username)
        if r.status_code == 204:
            repo = normalize(repo)
            if not Subscription.query.filter_by(user=user, repo=repo).first():
                sub = Subscription(repo=repo, user=user)
                db.session.add(sub)
                db.session.commit()
                return ''
    abort(400)


def notify(queue, title, text):
    print queue, title, text
    print requests.post(queue, {'title': title, 'body': text})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5003))
    app.run(host='0.0.0.0', port=port, debug=True)
