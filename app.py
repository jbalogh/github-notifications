from datetime import datetime
import json
import os

import urlparse

import requests

from flask import Flask, request, redirect, abort, session
from flaskext.sqlalchemy import SQLAlchemy

app = Flask(__name__)
db_url = os.environ.get('DATABASE_URL', 'sqlite:////tmp/test.db')
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
db = SQLAlchemy(app)

OAUTH_CLIENT = os.environ.get('OAUTH_CLIENT', '')
OAUTH_SECRET = os.environ.get('OAUTH_SECRET', '')

app.secret_key = os.environ.get('SECRET_KEY', 'secret key')


class Model(object):

    def __init__(self, **kw):
        for key, value in kw.items():
            setattr(self, key, value)


class User(Model, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created = db.Column(db.DateTime, default=datetime.now)
    username = db.Column(db.String(80), unique=True)
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
    if request.headers['X-Forwarded-Proto'] != 'https':
        response = redirect('https://github-notifications.herokuapp.com', 301)
        response.headers['Strict-Transport-Security'] = 'max-age=15768000'
        return response
    return open('index.html').read()


@app.route('/queue', methods=['POST'])
def add_queue():
    queue = request.form['queue']
    username = session['username']
    user = User.query.filter_by(username=username).first_or_404()
    if user.push_url != queue:
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
        username = json.loads(r.text)['login']
        if not User.query.filter_by(username=username).first():
            user = User(username=username)
            db.session.add(user)
            db.session.commit()

        session['username'] = username
        response = redirect('/')
        response.set_cookie('access_token', token)
        response.set_cookie('username', username);
        return response

    return redirect('/')


@app.route('/hook', methods=['POST'])
def hook():
    payload = json.loads(request.form['payload'])
    import pprint; pprint.pprint(payload)
    repo = payload['repository']
    if not payload['commits']:
        return ''

    commit = payload['commits'][0]

    title = '%s - %s' % (repo['name'], commit['author']['name'])
    body = commit['message']
    action = commit['url']
    if len(payload['commits']) > 1:
        body += ' (and %s more)' % (len(payload['commits']) - 1)
        before, after = payload['before'][:8], payload['after'][:8]
        action = payload['compare']

    repo_slug = normalize(repo['url'])
    q = User.query.join(User.subscriptions).filter(Subscription.repo == repo_slug)
    for user in q.all():
        if user.push_url:
            notify(user.push_url, title, body, action)
    return ''


def normalize(repo_url):
    return '/'.join(repo_url.split('/')[-2:])


@app.route('/subscribe', methods=['POST'])
def subscribe():
    repo = request.form['repo']
    username = session['username']

    user = User.query.filter_by(username=username).first_or_404()
    r = requests.get(repo + '/collaborators/%s' % user.username)
    if r.status_code == 204:
        repo = normalize(repo)
        if not Subscription.query.filter_by(user=user, repo=repo).first():
            sub = Subscription(repo=repo, user=user)
            db.session.add(sub)
            db.session.commit()
            return ''
    abort(400)


@app.route('/unsubscribe', methods=['POST'])
def unsubscribe():
    repo = normalize(request.form['repo'])
    username = session['username']

    user = User.query.filter_by(username=username).first_or_404()
    obj = Subscription.query.filter_by(user=user, repo=repo).first_or_404()
    db.session.delete(obj)
    db.session.commit()
    return ''


def notify(queue, title, text, action=None):
    msg = {'title': title, 'body': text, 'actionUrl': action}
    msg = dict((k, v) for k, v in msg.items() if v)
    print requests.post(queue, msg)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5003))
    app.run(host='0.0.0.0', port=port)
