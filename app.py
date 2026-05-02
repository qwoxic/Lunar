import os
from flask import Flask, render_template, redirect, url_for, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import pytz

app = Flask(__name__)
app.config.update(
    SECRET_KEY='Lunar_Yandex_Lyceum_2026',
    SQLALCHEMY_DATABASE_URI='sqlite:///lunar.db',
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    UPLOAD_FOLDER='static/uploads'
)

db = SQLAlchemy(app)
socketio = SocketIO(app, async_mode='threading')

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    password = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200), nullable=True)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text, nullable=False)
    file_path = db.Column(db.String(200), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(pytz.timezone('Europe/Moscow')))

def format_date(dt):
    now = datetime.now(pytz.timezone('Europe/Moscow'))
    if dt.date() == now.date(): return "Сегодня"
    if dt.date() == (now - timedelta(days=1)).date(): return "Вчера"
    return dt.strftime('%d %B')

@app.route('/')
def index():
    if 'uid' not in session: return redirect(url_for('login'))
    user = User.query.get(session['uid'])
    if not user:
        session.clear()
        return redirect(url_for('login'))
    search_q = request.args.get('search')
    recipient = User.query.filter_by(username=search_q).first() if search_q else None
    if recipient:
        Message.query.filter_by(sender_id=recipient.id, recipient_id=user.id, is_read=False).update({'is_read': True})
        db.session.commit()
        history = Message.query.filter(
            ((Message.sender_id == user.id) & (Message.recipient_id == recipient.id)) |
            ((Message.sender_id == recipient.id) & (Message.recipient_id == user.id))
        ).order_by(Message.timestamp.asc()).all()
    else: history = []
    raw_chats = db.session.query(User).join(Message, (User.id == Message.sender_id) | (User.id == Message.recipient_id))\
        .filter((Message.sender_id == user.id) | (Message.recipient_id == user.id))\
        .filter(User.id != user.id).distinct().all()
    chats_with_unread = []
    for c in raw_chats:
        unread = Message.query.filter_by(sender_id=c.id, recipient_id=user.id, is_read=False).count()
        chats_with_unread.append({'user': c, 'unread': unread})
    return render_template('chat.html', recipient=recipient, msgs=history, chats=chats_with_unread, user=user, format_date=format_date)

@app.route('/set_avatar', methods=['POST'])
def set_avatar():
    file = request.files.get('avatar')
    if file:
        fname = secure_filename(f"av_{session['uid']}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        User.query.get(session['uid']).avatar = fname
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files.get('file')
    rid = request.form.get('rid')
    if file and rid:
        fname = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        db.session.add(Message(sender_id=session['uid'], recipient_id=rid, content=fname, file_path=fname))
        db.session.commit()
        return redirect(url_for('index', search=User.query.get(rid).username))
    return redirect(url_for('index'))

@app.route('/api/profile/<int:user_id>')
def api_profile(user_id):
    u = User.query.get_or_404(user_id)
    return jsonify({"username": u.username, "name": u.display_name, "avatar": u.avatar})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['u']).first()
        if u and check_password_hash(u.password, request.form['p']):
            session['uid'] = u.id
            return redirect(url_for('index'))
    return render_template('auth.html', mode='login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.query.filter_by(username=request.form['u']).first(): return "Ник занят"
        pw = generate_password_hash(request.form['p'], method='pbkdf2:sha256')
        new_u = User(username=request.form['u'], display_name=request.form['d'], password=pw)
        db.session.add(new_u); db.session.commit()
        session['uid'] = new_u.id
        return redirect(url_for('index'))
    return render_template('auth.html', mode='reg')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@socketio.on('join')
def on_join(data):
    u1, u2 = sorted([int(session['uid']), int(data['rid'])])
    join_room(f"dm_{u1}_{u2}")

@socketio.on('send')
def handle_send(data):
    if not data['msg'].strip(): return
    m = Message(sender_id=session['uid'], recipient_id=data['rid'], content=data['msg'])
    db.session.add(m); db.session.commit()
    u1, u2 = sorted([int(session['uid']), int(data['rid'])])
    emit('new', {'msg': data['msg'], 'sid': session['uid'], 't': m.timestamp.strftime('%H:%M')}, room=f"dm_{u1}_{u2}")

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    with app.app_context(): db.create_all()
    socketio.run(app, debug=True, host='127.0.0.1', port=5000)
