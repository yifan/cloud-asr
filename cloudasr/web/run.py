import os
from flask import Flask, flash, render_template, redirect, request, url_for, session, jsonify
from flask.ext.login import LoginManager, login_user, logout_user, login_required, current_user
from flask.ext.googlelogin import GoogleLogin
from flask.ext.principal import Principal, Permission, RoleNeed, UserNeed, AnonymousIdentity, Identity, identity_loaded, identity_changed
from flask.ext.sqlalchemy import SQLAlchemy
from cloudasr.schema import db
from cloudasr.models import UsersModel, RecordingsModel, WorkerTypesModel


app = Flask(__name__)
app.config.update(
    SECRET_KEY = '12345',
    DEBUG = 'DEBUG' in os.environ,
    GOOGLE_LOGIN_CLIENT_ID = os.environ['GOOGLE_LOGIN_CLIENT_ID'],
    GOOGLE_LOGIN_CLIENT_SECRET = os.environ['GOOGLE_LOGIN_CLIENT_SECRET'],
    GOOGLE_LOGIN_SCOPES = 'https://www.googleapis.com/auth/userinfo.email',
    SQLALCHEMY_DATABASE_URI = os.environ['CONNECTION_STRING']
)

login_manager = LoginManager(app)
google_login = GoogleLogin(app, login_manager)

principals = Principal(app)
admin_permission = Permission(RoleNeed('admin'))

db.init_app(app)
users_model = UsersModel(db.session)
worker_types_model = WorkerTypesModel(db.session)
recordings_model = RecordingsModel(db.session, worker_types_model)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/demo')
@app.route('/demo/<model>')
def demo(model=None):
    return render_template('demo.html', api_url = os.environ['API_URL'], model = model)

@app.route('/available-workers')
def available_workers():
    return jsonify({"workers": worker_types_model.get_available_workers()})

@app.route('/documentation')
def documentation():
    return render_template('documentation.html')

@app.route('/worker-types')
def worker_types():
    return render_template('worker_types.html', worker_types=worker_types_model.get_models())

@app.route('/transcribe/<model>')
@app.route('/transcribe/<int:id>')
def transcribe(id = None, model = None):
    if id is not None:
        recording = recordings_model.get_recording(id)
        backlink = request.args.get('next') or url_for('transcribe', model = recording.model)

    if model is not None:
        recording = recordings_model.get_random_recording(model)
        backlink = url_for('transcribe', model = recording.model)

    return render_template('transcribe.html', recording=recording, backlink=backlink)

@app.route('/save-transcription', methods=['POST'])
def save_transcription():
    flash('Recording was successfully transcribed')

    recordings_model.add_transcription(
        current_user.get_id(),
        request.form['id'],
        request.form['transcription'],
        'native_speaker' in request.form,
        'offensive_language' in request.form,
        'not_a_speech' in request.form
    )

    return redirect(request.form['backlink'])

@app.route('/recordings/<model>/<int:page>')
@admin_permission.require()
def recordings(model, page):
    pagination = recordings_model.get_recordings(model).paginate(page, 10)
    recordings = pagination.items


    return render_template('recordings.html', recordings=recordings, model=model, pagination=pagination)

@app.route('/transcriptions/<id>')
@admin_permission.require()
def transcriptions(id):
    return render_template('transcriptions.html', recording=recordings_model.get_recording(id))

@app.route('/new-worker')
@admin_permission.require()
def new_worker():
    return render_template('edit_worker.html', worker = {"id": None})

@app.route('/edit-worker/<model>')
@admin_permission.require()
def edit_worker(model):
    return render_template('edit_worker.html', worker = worker_types_model.get_worker_type(model))

@app.route('/save-worker-description', methods=['POST'])
@admin_permission.require()
def save_worker_description():
    flash('Worker\'s description was successfully saved')
    worker_types_model.edit_worker(request.form['id'], request.form['name'], request.form['description'])
    return redirect(url_for('worker_types'))

@app.route('/login/google')
@google_login.oauth2callback
def login_google(token, userinfo, **params):
    login_user(users_model.upsert_user(userinfo))

    identity = Identity(userinfo['id'])
    identity_changed.send(app, identity = identity)

    return redirect(url_for('index'))

@app.route('/logout')
@login_required
def logout():
    logout_user()

    for key in ['identity.name', 'identity.auth_type']:
        session.pop(key, None)
    identity_changed.send(app, identity=AnonymousIdentity())

    return redirect(url_for('index'))

@app.errorhandler(403)
def page_not_found(e):
    return render_template('403.html'), 403

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(e):
    return render_template('500.html'), 500

@app.context_processor
def inject_google_login_url():
    return dict(
        google_login_url = google_login.login_url(redirect_uri=url_for('login_google', _external=True)),
        ga_tracking_id = os.environ.get('GA_TRACKING_ID', None),
        logout_url = url_for('logout')
    )

@login_manager.user_loader
def load_user(id):
    return users_model.get_user(id)

@identity_loaded.connect_via(app)
def on_identity_loaded(sender, identity):
    identity.user = current_user

    if hasattr(current_user, 'id'):
        identity.provides.add(UserNeed(current_user.id))

    if hasattr(current_user, 'admin') and current_user.admin:
        identity.provides.add(RoleNeed('admin'))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
