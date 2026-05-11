import os
import base64
import io
import pytz
from datetime import datetime, timedelta
from flask import Flask, render_template, redirect, url_for, request, session, jsonify, send_file
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from models import db, User, Message

app = Flask(__name__)
app.config.update(
    SECRET_KEY='Lunar_Yandex_Lyceum_2026',
    SQLALCHEMY_DATABASE_URI='sqlite:///lunar.db',
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    UPLOAD_FOLDER='static/uploads',
    MAX_CONTENT_LENGTH=16 * 1024 * 1024
)

db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*")

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

MOSCOW_TZ = pytz.timezone('Europe/Moscow')

def format_date(dt):
    if dt.tzinfo is None:
        dt = MOSCOW_TZ.localize(dt)
    now = datetime.now(MOSCOW_TZ)
    if dt.date() == now.date():
        return "Сегодня"
    if dt.date() == (now - timedelta(days=1)).date():
        return "Вчера"
    return dt.strftime('%d %b')

@app.route('/')
def index():
    uid = session.get('uid')
    if not uid:
        return redirect(url_for('login'))
    u = db.session.get(User, uid)
    if not u:
        return redirect(url_for('login'))

    q = request.args.get('search', '').strip()
    target = None
    history = []
    
    if q:
        target = User.query.filter_by(username=q).first()
        if target:
            Message.query.filter_by(sender_id=target.id, recipient_id=u.id, is_read=False).update({'is_read': True})
            db.session.commit()
            history = Message.query.filter(
                ((Message.sender_id == u.id) & (Message.recipient_id == target.id)) |
                ((Message.sender_id == target.id) & (Message.recipient_id == u.id))
            ).order_by(Message.timestamp.asc()).all()

    sub_ids = db.session.query(Message.sender_id).filter(Message.recipient_id == u.id).union(
        db.session.query(Message.recipient_id).filter(Message.sender_id == u.id)
    ).all()
    u_ids = [i[0] for i in sub_ids if i[0] != u.id]

    clist = []
    if u_ids:
        users = User.query.filter(User.id.in_(u_ids)).all()
        unread_counts = {}
        for uid_tmp in u_ids:
            cnt = Message.query.filter_by(sender_id=uid_tmp, recipient_id=u.id, is_read=False).count()
            if cnt:
                unread_counts[uid_tmp] = cnt
        for user in users:
            clist.append({'user': user, 'unread': unread_counts.get(user.id, 0)})
        clist.sort(key=lambda x: x['user'].id, reverse=True)
        
    return render_template('chat.html', user=u, recipient=target, msgs=history, chats=clist, format_date=format_date)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('u')).first()
        if user and check_password_hash(user.password, request.form.get('p')):
            session['uid'] = user.id
            user.is_online = True
            db.session.commit()
            return redirect(url_for('index'))
    return render_template('auth.html', mode='login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = request.form.get('u')
        d = request.form.get('d')
        p = request.form.get('p')
        if not u or not d or not p:
            return redirect(url_for('register'))
        if User.query.filter_by(username=u).first():
            return redirect(url_for('register'))
        new = User(username=u, display_name=d, password=generate_password_hash(p))
        db.session.add(new)
        db.session.commit()
        session['uid'] = new.id
        new.is_online = True
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('auth.html', mode='reg')

@app.route('/logout')
def logout():
    u = db.session.get(User, session.get('uid'))
    if u:
        u.is_online = False
        db.session.commit()
        socketio.emit('st_ch', {'uid': u.id, 'on': False})
    session.clear()
    return redirect(url_for('login'))

@app.route('/set_avatar', methods=['POST'])
def set_avatar():
    uid = session.get('uid')
    if not uid:
        return redirect(url_for('login'))
    u = db.session.get(User, uid)
    if not u:
        return redirect(url_for('login'))
    
    if 'avatar' not in request.files:
        return redirect(url_for('index'))
    
    file = request.files['avatar']
    if file.filename == '':
        return redirect(url_for('index'))
    
    if file and allowed_file(file.filename):
        filename = f"user_{uid}_{secure_filename(file.filename)}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        if u.avatar:
            old = os.path.join(app.config['UPLOAD_FOLDER'], u.avatar)
            if os.path.exists(old):
                try:
                    os.remove(old)
                except:
                    pass
        u.avatar = filename
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/mark_read', methods=['POST'])
def mark_read():
    uid = session.get('uid')
    sid = request.json.get('sender_id')
    if uid and sid:
        msgs = Message.query.filter_by(sender_id=sid, recipient_id=uid, is_read=False).all()
        for m in msgs:
            m.is_read = True
        db.session.commit()
        room = f"r_{min(int(uid), int(sid))}_{max(int(uid), int(sid))}"
        socketio.emit('msg_read', {'sender': sid, 'reader': uid}, room=room)
    return jsonify({'ok': True})

@app.route('/download/<int:mid>')
def download_file(mid):
    uid = session.get('uid')
    if not uid:
        return redirect(url_for('login'))
    m = db.session.get(Message, mid)
    if not m or (m.sender_id != uid and m.recipient_id != uid):
        return "Нет доступа", 403
    if not m.file_data:
        return "Файл не найден", 404
    return send_file(
        io.BytesIO(m.file_data),
        download_name=m.file_name,
        as_attachment=True
    )

@socketio.on('join')
def on_join(data):
    uid = session.get('uid')
    rid = data.get('rid')
    if uid and rid:
        room = f"r_{min(int(uid), int(rid))}_{max(int(uid), int(rid))}"
        join_room(room)

@socketio.on('send')
def on_send(data):
    uid = session.get('uid')
    rid = data.get('rid')
    txt = data.get('msg', '').strip()
    if not txt or not rid or not uid:
        return
    m = Message(sender_id=uid, recipient_id=rid, content=txt)
    db.session.add(m)
    db.session.commit()
    room = f"r_{min(int(uid), int(rid))}_{max(int(uid), int(rid))}"
    emit('new', {
        'msg': txt,
        'sid': uid,
        't': m.timestamp.strftime('%H:%M'),
        'mid': m.id
    }, room=room)

@socketio.on('send_file')
def on_send_file(data):
    uid = session.get('uid')
    rid = data.get('rid')
    name = data.get('name')
    raw = data.get('data')
    if not uid or not rid or not name or not raw:
        return
    header, b64 = raw.split(',', 1)
    file_bytes = base64.b64decode(b64)
    m = Message(sender_id=uid, recipient_id=rid, file_name=name, file_data=file_bytes)
    db.session.add(m)
    db.session.commit()
    room = f"r_{min(int(uid), int(rid))}_{max(int(uid), int(rid))}"
    emit('new', {
        'file': name,
        'sid': uid,
        't': m.timestamp.strftime('%H:%M'),
        'mid': m.id
    }, room=room)

@socketio.on('typing')
def on_typing(data):
    uid = session.get('uid')
    rid = data.get('rid')
    if uid and rid:
        room = f"r_{min(int(uid), int(rid))}_{max(int(uid), int(rid))}"
        emit('is_tp', {'state': data.get('state', 0)}, room=room, include_self=False)

@socketio.on('del_all')
def on_delete(data):
    mid = data.get('mid')
    if not mid:
        return
    m = db.session.get(Message, mid)
    if m and m.sender_id == session.get('uid'):
        rid = m.recipient_id
        db.session.delete(m)
        db.session.commit()
        room = f"r_{min(int(session['uid']), int(rid))}_{max(int(session['uid']), int(rid))}"
        emit('m_del', {'mid': mid}, room=room)

@socketio.on('connect')
def on_connect():
    uid = session.get('uid')
    if uid:
        u = db.session.get(User, uid)
        if u:
            u.is_online = True
            db.session.commit()
            emit('st_ch', {'uid': u.id, 'on': True}, broadcast=True)

@socketio.on('disconnect')
def on_disconnect():
    uid = session.get('uid')
    if uid:
        u = db.session.get(User, uid)
        if u:
            u.is_online = False
            db.session.commit()
            emit('st_ch', {'uid': u.id, 'on': False}, broadcast=True)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
