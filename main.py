import os, time, json, datetime
from threading import Thread, Event
from flask import Flask, request, render_template_string, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "devkey")

# Simple SQLite DB
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///users.db"
db = SQLAlchemy(app)

# Admin credentials
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password_hash = db.Column(db.String(200))
    approved = db.Column(db.Boolean, default=False)
    def check(self, pwd): return check_password_hash(self.password_hash, pwd)

# Tasks
tasks, LOG_DIR = {}, "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# UI
INDEX_HTML = """
<!doctype html><html><body>
<h3>FB Auto Comment Tool</h3>
<form method="post" enctype="multipart/form-data">
  <input type="file" name="tokenFile" required><br>
  <input name="postId" placeholder="Post ID"><br>
  <input name="prefix" placeholder="Prefix"><br>
  <input type="number" name="time" value="5"><br>
  <input type="file" name="txtFile" required><br>
  <button>Start Task</button>
</form>
<hr>
<form method="post" action="/stop">
  <input name="taskId" placeholder="Task ID"><br>
  <button>Stop</button>
</form>
</body></html>
"""

# Worker
def worker(tid,tokens,post,prefix,interval,comments):
    stop=tasks[tid]["stop"]; log=tasks[tid]["log"]
    i=j=0
    while not stop.is_set():
        data={"time":datetime.datetime.utcnow().isoformat(),"msg":f"{prefix} {comments[i]}"}
        with open(log,"a") as f: f.write(json.dumps(data)+"\n")
        i=(i+1)%len(comments); j=(j+1)%len(tokens); time.sleep(interval)

# Auth helpers
def login_required(f):
    def w(*a,**k):
        if not session.get("uid"): return redirect("/login")
        u=User.query.get(session["uid"])
        if not u or not u.approved: session.clear(); return redirect("/login")
        return f(*a,**k)
    w.__name__=f.__name__; return w

# Routes
@app.route("/",methods=["GET","POST"])
@login_required
def index():
    if request.method=="POST":
        tokens=request.files["tokenFile"].read().decode().splitlines()
        post,prefix,interval=request.form["postId"],request.form["prefix"],float(request.form["time"])
        comments=request.files["txtFile"].read().decode().splitlines()
        tid=os.urandom(4).hex(); log=os.path.join(LOG_DIR,f"{tid}.log")
        tasks[tid]={"stop":Event(),"log":log}
        Thread(target=worker,args=(tid,tokens,post,prefix,interval,comments),daemon=True).start()
        return f"Task started {tid}"
    return render_template_string(INDEX_HTML)

@app.route("/stop",methods=["POST"])
@login_required
def stop():
    tid=request.form["taskId"]
    if tid in tasks: tasks[tid]["stop"].set(); return f"Stopped {tid}"
    return redirect("/")

@app.route("/register",methods=["GET","POST"])
def register():
    if request.method=="POST":
        u,p=request.form["u"],request.form["p"]
        if User.query.filter_by(username=u).first(): return "User exists"
        db.session.add(User(username=u,password_hash=generate_password_hash(p))); db.session.commit()
        return "Registered, wait for approval"
    return "<form method=post><input name=u><input type=password name=p><button>Register</button></form>"

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        u,p=request.form["u"],request.form["p"]
        if u==ADMIN_USER and p==ADMIN_PASS: session["admin"]=True; return redirect("/admin")
        usr=User.query.filter_by(username=u).first()
        if usr and usr.check(p) and usr.approved: session["uid"]=usr.id; return redirect("/")
        return "Invalid or not approved"
    return "<form method=post><input name=u><input type=password name=p><button>Login</button></form>"

@app.route("/logout")
def logout(): session.clear(); return redirect("/login")

@app.route("/admin")
def admin():
    if not session.get("admin"): return redirect("/login")
    pend=User.query.filter_by(approved=False).all()
    return "".join(f"<p>{x.username} <a href='/approve/{x.id}'>Approve</a></p>" for x in pend)

@app.route("/approve/<int:uid>")
def approve(uid):
    if not session.get("admin"): return redirect("/login")
    u=User.query.get(uid); u.approved=True; db.session.commit(); return redirect("/admin")

@app.before_first_request
def init(): db.create_all()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)))
