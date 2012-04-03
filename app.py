from datetime import datetime
import json
import logging
from logging.handlers import SMTPHandler
import os
import time
import urlparse

import redis as redislib
import requests

from flask import Flask, request, redirect, abort, session, jsonify
from flaskext.sqlalchemy import SQLAlchemy

app = Flask(__name__)
db_url = os.environ.get('DATABASE_URL', 'sqlite:////tmp/test.db')
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
db = SQLAlchemy(app)

OAUTH_CLIENT = os.environ.get('OAUTH_CLIENT', '')
OAUTH_SECRET = os.environ.get('OAUTH_SECRET', '')

STATIC_URL = os.environ.get('STATIC_URL', 'static')

app.secret_key = os.environ.get('SECRET_KEY', 'secret key')

redis_url = urlparse.urlparse(os.environ.get('REDISTOGO_URL',
                                             'redis://localhost:6379'))
redis = redislib.Redis(host=redis_url.hostname, port=redis_url.port,
                       password=redis_url.password)


if os.environ.get('SENDGRID_USERNAME'):
    mail_handler = SMTPHandler('smtp.sendgrid.net',
                               'errors@jbalogh.me',
                               ['errors@jbalogh.me'],
                               '[Error] Heroku',
                               credentials=(os.environ['SENDGRID_USERNAME'],
                                            os.environ['SENDGRID_PASSWORD']))
    mail_handler.setLevel(logging.ERROR)
    app.logger.addHandler(mail_handler)
    mail_handler.setFormatter(logging.Formatter("""\
Message type:       %(levelname)s
Location:           %(pathname)s:%(lineno)d
Module:             %(module)s
Function:           %(funcName)s
Time:               %(asctime)s

Message:

%(message)s"""))


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

    def __repr__(self):
        return self.username


class Subscription(Model, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # username/repo-name
    repo = db.Column(db.String(256))
    created = db.Column(db.DateTime, default=datetime.now)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship('User',
                           backref=db.backref('subscriptions', lazy='dynamic'))

    def __repr__(self):
        return self.repo


def stat(name, bucket='stats'):
    start = time.time()
    now = datetime.now()
    pipe = redis.pipeline()
    pipe.hincrby(bucket, name, 1)
    pipe.incr(name + now.strftime(':%Y-%m-%d:%H:%M'))
    pipe.incr(name + now.strftime(':%Y-%m-%d:%H'))
    pipe.incr(name + now.strftime(':%Y-%m-%d'))
    pipe.execute()
    print 'redis: %.2f' % (time.time() - start)


STATS = {
    'http-redirect': 'Redirect HTTP to HTTPS',
    'homepage': '/',
    'queue': '/queue',
    'new-queue': 'New Queue',
    'update-queue': 'Update Queue',
    'oauth': '/oauth',
    'new-user': 'New User',
    'hook': '/hook',
    'notify': 'Send Notification',
    'subscribe': '/subscribe',
    'add-subscription': 'Add subscription',
    'unsubscribe': 'Unsubscribe',
    'stat': '/stat',
    'test-hook': 'Test Hook',
    'add-hook': 'Add Hook',
    'hook-fail': 'Adding Hook Failed',
    'remove-hook': 'Remove Hook',
    'step-1': 'Get Add-on',
    'step-2': 'Authorize',
    'step-3': 'Add Repos',
    'check-perm': 'Check Permission succeeded',
    'request-perm': 'Request Permission succeeded',
    'push-url': 'Have push URL',
    'oauthd': 'OAuth Success',
    'nav-timing': 'Navigation Timing',
    'no-nav-timing': 'No Navigation Timer',
}


@app.route('/', methods=['GET'])
def root():
    if not app.debug and request.headers['X-Forwarded-Proto'] != 'https':
        stat('http-redirect')
        response = redirect('https://github-notifications.herokuapp.com', 301)
        response.headers['Strict-Transport-Security'] = 'max-age=15768000'
        return response
    stat('homepage')
    return open('index.html').read() % {'STATIC': STATIC_URL}


@app.route('/queue', methods=['POST'])
def add_queue():
    stat('queue')
    queue = request.form['queue']
    username = session['username']
    user = User.query.filter_by(username=username).first_or_404()
    new_user = user.push_url is None
    if user.push_url != queue:
        if not new_user:
            stat('update-queue')
        print ('Adding push URL.' if new_user else 'Updating push URL.')
        user.push_url = queue
        db.session.add(user)
        db.session.commit()
    if new_user:
        stat('new-queue')
        notify(queue, 'Welcome to Github Notifications!',
               'So glad to have you %s.' % user.username)
    return ''


@app.route('/oauth', methods=['GET'])
def oauth():
    stat('oauth')
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
            stat('new-user')
            print 'New user:', username
            user = User(username=username)
            db.session.add(user)
            db.session.commit()

        session['username'] = username
        response = redirect('/')
        response.set_cookie('access_token', token)
        response.set_cookie('username', username)
        return response

    return redirect('/')


@app.route('/hook', methods=['POST'])
def hook():
    stat('hook')
    payload = json.loads(request.form['payload'])
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
    stat(repo_slug, bucket='hooks')
    print 'Sending hook for:', repo_slug
    q = User.query.join(User.subscriptions).filter(Subscription.repo == repo_slug)
    for user in q.all():
        if user.push_url:
            notify(user.push_url, title, body, action)
    return ''


def normalize(repo_url):
    return '/'.join(repo_url.split('/')[-2:])


@app.route('/subscribe', methods=['POST'])
def subscribe():
    stat('subscribe')
    repo = request.form['repo']
    username = session['username']

    user = User.query.filter_by(username=username).first_or_404()
    r = requests.get(repo + '/collaborators/%s' % user.username)
    if r.status_code == 204:
        repo = normalize(repo)
        if not Subscription.query.filter_by(user=user, repo=repo).first():
            stat('add-subscription')
            print 'Adding a subscription for:', repo
            sub = Subscription(repo=repo, user=user)
            db.session.add(sub)
            db.session.commit()
            return ''
    abort(400)


@app.route('/unsubscribe', methods=['POST'])
def unsubscribe():
    stat('unsubscribe')
    repo = normalize(request.form['repo'])
    username = session['username']

    user = User.query.filter_by(username=username).first_or_404()
    obj = Subscription.query.filter_by(user=user, repo=repo).first_or_404()
    db.session.delete(obj)
    db.session.commit()
    return jsonify(count=Subscription.query.filter_by(repo=repo).count())


@app.route('/stats', methods=['POST'])
def add_stat():
    stat('add-stat')
    for key in request.form:
        stat(key)
    return ''


@app.route('/nav-timing', methods=['POST'])
def nav_timing():
    start = time.time()
    pipe = redis.pipeline()
    pipe.hincrby('stats', 'nav-timing', 1)
    pipe.rpush('dns', request.form['dns'])
    pipe.rpush('connect', request.form['connect'])
    pipe.rpush('response', request.form['response'])
    pipe.rpush('interactive', request.form['interactive'])
    pipe.rpush('loaded', request.form['loaded'])
    pipe.rpush('total', request.form['total'])
    pipe.execute()
    print 'redis: %.2f' % (time.time() - start)
    return ''


def notify(queue, title, text, action=None):
    stat('notify')
    msg = {'title': title, 'body': text, 'actionUrl': action}
    msg = dict((k, v) for k, v in msg.items() if v)
    response = requests.post(queue, msg)
    print 'Sent notification:', response
    stat('notify:%s' % response.status_code)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5003))
    app.run(host='0.0.0.0', port=port, debug=True)
