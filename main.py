import os, time, json, datetime
from threading import Thread, Event
from flask import Flask, request, render_template_string, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

# Database (Render ke liye PostgreSQL, warna local SQLite)
db_url = os.environ.get("DATABASE_URL", "sqlite:///users.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Admin credentials
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

tasks, LOG_DIR = {}, "logs"
os.makedirs(LOG_DIR, exist_ok=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    approved = db.Column(db.Boolean, default=False)

    def check_password(self, pwd):
        return check_password_hash(self.password_hash, pwd)

INDEX_HTML = """
<!doctype html>
<html><head>
<title>FB Auto Tool</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head><body><div class="container mt-4">
<h3>FB Auto Comment Tool</h3>
<form method="post" enctype="multipart/form-data">
  <input type="file" name="tokenFile" class="form-control mb-2" required>
  <input type="text" name="postId" placeholder="Post ID" class="form-control mb-2" required>
  <input type="text" name="prefix" placeholder="Prefix" class="form-control mb-2" required>
  <input type="number" name="time" value="240" class="form-control mb-2" required>
  <input type="file" name="txtFile" class="form-control mb-2" required>
  <button class="btn btn-primary w-100">Start Task</button>
</form><hr>
<form method="post" action="/stop">
  <input type="text" name="taskId" placeholder="Task ID" class="form-control mb-2">
  <button class="btn btn-danger w-100">Stop Task</button>
</form>
</div></body></html>
"""

def worker(task_id, tokens, post_id, prefix, interval, comments):
    stop_event, log_file = tasks[task_id]["stop"], tasks[task_id]["log"]
    i, j = 0, 0
    while not stop_event.is_set():
        msg = {"time": datetime.datetime.utcnow().isoformat(), "msg": f"{prefix} {comments[i]}"}
        with open(log_file, "a") as f: f.write(json.dumps(msg) + "\n")
        i, j = (i+1) % len(comments), (j+1) % len(tokens)
        time.sleep(interval)

def login_required(f):
    def wrap(*a, **k):
        if not session.get("user_id"): return redirect(url_for("login"))
        u = User.query.get(session["user_id"])
        if not u or not u.approved: session.clear(); return redirect(url_for("login"))
        return f(*a, **k)
    wrap.__name__ = f.__name__; return wrap

def admin_required(f):
    def wrap(*a, **k):
        if not session.get("is_admin"): return redirect(url_for("admin_login"))
        return f(*a, **k)
    wrap.__name__ = f.__name__; return wrap

@app.route("/", methods=["GET","POST"])
@login_required
def index():
    if request.method == "POST":
        tokens = request.files["tokenFile"].read().decode().splitlines()
        post_id, prefix = request.form["postId"], request.form["prefix"]
        interval = float(request.form["time"])
        comments = request.files["txtFile"].read().decode().splitlines()
        tid, log_file = os.urandom(4).hex(), os.path.join(LOG_DIR, f"{os.urandom(4).hex()}.log")
        tasks[tid] = {"stop": Event(), "log": log_file}
        Thread(target=worker, args=(tid,tokens,post_id,prefix,interval,comments), daemon=True).start()
        flash(f"Task started {tid}")
    return render_template_string(INDEX_HTML)

@app.route("/stop", methods=["POST"]); @login_required
def stop(): tid=request.form["taskId"]; 
if tid in tasks: tasks[tid]["stop"].set(); flash(f"Stopped {tid}"); return redirect("/")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        u,p=request.form["username"],request.form["password"]
        if User.query.filter_by(username=u).first(): return "Username taken"
        db.session.add(User(username=u,password_hash=generate_password_hash(p))); db.session.commit()
        return "Registered, wait for approval"
    return "<form method=post><input name=username><input type=password name=password><button>Register</button></form>"

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        u,p=request.form["username"],request.form["password"]
        if u==ADMIN_USERNAME and p==ADMIN_PASSWORD: session["is_admin"]=True; return redirect("/admin")
        user=User.query.filter_by(username=u).first()
        if user and user.check_password(p) and user.approved: session["user_id"]=user.id; return redirect("/")
        return "Invalid or not approved"
    return "<form method=post><input name=username><input type=password name=password><button>Login</button></form>"

@app.route("/logout"); def logout(): session.clear(); return redirect("/login")

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method=="POST" and request.form["username"]==ADMIN_USERNAME and request.form["password"]==ADMIN_PASSWORD:
        session["is_admin"]=True; return redirect("/admin")
    return "<form method=post><input name=username><input type=password name=password><button>Login</button></form>"

@app.route("/admin"); @admin_required
def admin():
    pending=User.query.filter_by(approved=False).all()
    return "<h3>Admin</h3>"+"".join(f"<p>{u.username} <a href='/admin/approve/{u.id}'>Approve</a></p>" for u in pending)

@app.route("/admin/approve/<int:uid>"); @admin_required
def approve(uid): u=User.query.get(uid); u.approved=True; db.session.commit(); return redirect("/admin")

@app.before_first_request
def init(): db.create_all()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
