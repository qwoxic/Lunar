from flask import Flask, render_template, redirect, request, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config.update(SECRET_KEY='team', SQLALCHEMY_DATABASE_URI='sqlite:///lunar.db')
db = SQLAlchemy(app)

friends = db.Table('friends',
    db.Column('u1', db.ForeignKey('user.id')),
    db.Column('u2', db.ForeignKey('user.id'))
)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    display_name = db.Column(db.String(50))
    password_hash = db.Column(db.String(128))
    contacts = db.relationship('User', secondary=friends, 
                               primaryjoin=id==friends.c.u1, 
                               secondaryjoin=id==friends.c.u2)

@app.route('/')
def index():
    if 'id' not in session: return redirect('/login')
    me = User.query.get(session['id'])
    q = request.args.get('q')
    chat_id = request.args.get('chat')
    res = User.query.filter(User.username.ilike(f'%{q}%'), User.id != me.id).all() if q else []
    other = User.query.get(chat_id) if chat_id else None
    return render_template('chat.html', me=me, res=res, other=other)

@app.route('/add/<int:id>')
def add(id):
    me, u = User.query.get(session['id']), User.query.get(id)
    if u and u not in me.contacts:
        me.contacts.append(u); db.session.commit()
    return redirect('/')

@app.route('/del/<int:id>')
def delete(id):
    me = User.query.get(session['id'])
    u = User.query.get(id)
    if u in me.contacts:
        me.contacts.remove(u); db.session.commit()
    return redirect('/')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and check_password_hash(u.password_hash, request.form['password']):
            session['id'] = u.id
            return redirect('/')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        h = generate_password_hash(request.form['password'])
        db.session.add(User(username=request.form['username'], display_name=request.form['display_name'], password_hash=h))
        db.session.commit()
        return redirect('/login')
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True)
