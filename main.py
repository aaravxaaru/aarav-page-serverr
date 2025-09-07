import os
import time
import json
import datetime
from threading import Thread, Event
from flask import Flask, request, render_template_string, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# -----------------------
# APP CONFIG
# -----------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "users.db")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + DB_PATH
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Admin credentials (from env or default)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

tasks = {}
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# -----------------------
# DB MODEL
# -----------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def check_password(self, pwd):
        return check_password_hash(self.password_hash, pwd)

# -----------------------
# HTML (Unchanged Old UI)
# -----------------------
INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FB Auto Comment Tool</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
  <div class="container mt-4">
    <h3 class="mb-3">FB Auto Comment Tool</h3>
    <form method="post" enctype="multipart/form-data">
      <input type="file" name="tokenFile" class="form-control mb-2" required>
      <input type="text" name="postId" placeholder="Post ID" class="form-control mb-2" required>
      <input type="text" name="prefix" placeholder="Prefix" class="form-control mb-2" required>
      <input type="number" name="time" value="240" class="form-control mb-2" required>
      <input type="file" name="txtFile" class="form-control mb-2" required>
      <button class="btn btn-primary w-100">Start Task</button>
    </form>
    <hr>
    <form method="post" action="/stop">
      <input type="text" name="taskId" placeholder="Task ID to stop" class="form-control mb-2">
      <button class="btn btn-danger w-100">Stop Task</button>
    </form>
  </div>
</body>
</html>
"""

# -----------------------
# WORKER
# -----------------------
def worker_simulate(task_id, tokens, post_id, prefix, interval, comments):
    meta = tasks.get(task_id)
    if not meta:
        return
    stop_event = meta["stop"]
    log_path = meta["log_file"]

    idx_comment = 0
    idx_token = 0
    while not stop_event.is_set():
        try:
            msg_text = comments[idx_comment]
            token_used = tokens[idx_token]
            prepared = {
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "post_id": post_id,
                "token_preview": token_used[:8] + "...",
                "prefix": prefix,
                "message": f"{prefix} {msg_text}"
            }
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(json.dumps(prepared) + "\n")
            idx_comment = (idx_comment + 1) % len(comments)
            idx_token = (idx_token + 1) % len(tokens)
        except Exception as e:
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(json.dumps({"error": str(e)}) + "\n")
        time.sleep(max(1, float(interval)))

# -----------------------
# AUTH HELPERS
# -----------------------
def login_required(f):
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        u = User.query.get(session["user_id"])
        if not u or not u.approved:
            session.clear()
            flash("Account not approved yet", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def admin_required(f):
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# -----------------------
# ROUTES
# -----------------------
@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        token_file = request.files.get("tokenFile")
        tokens = token_file.read().decode("utf-8").splitlines()
        post_id = request.form.get("postId")
        prefix = request.form.get("prefix")
        interval = float(request.form.get("time", 10))
        txtfile = request.files.get("txtFile")
        comments = txtfile.read().decode("utf-8").splitlines()

        task_id = os.urandom(4).hex()
        log_file = os.path.join(LOG_DIR, f"{task_id}.log")
        stop_ev = Event()
        tasks[task_id] = {"stop": stop_ev, "log_file": log_file}

        t = Thread(target=worker_simulate, args=(task_id, tokens, post_id, prefix, interval, comments))
        t.daemon = True
        t.start()
        flash(f"Task started with ID {task_id}", "success")
    return render_template_string(INDEX_HTML)

@app.route("/stop", methods=["POST"])
@login_required
def stop_task():
    tid = request.form.get("taskId")
    if tid in tasks:
        tasks[tid]["stop"].set()
        flash(f"Task {tid} stopped", "info")
    return redirect(url_for("index"))

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")
        if User.query.filter_by(username=u).first():
            flash("Username exists", "danger")
            return redirect(url_for("register"))
        user = User(username=u, password_hash=generate_password_hash(p), approved=False)
        db.session.add(user)
        db.session.commit()
        flash("Registered. Wait for approval.", "info")
        return redirect(url_for("login"))
    return """<h2>Register</h2><form method="post">
              <input name="username"><br>
              <input type="password" name="password"><br>
              <button>Register</button></form>"""

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")
        if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
            session.clear()
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        user = User.query.filter_by(username=u).first()
        if user and user.check_password(p):
            if not user.approved:
                flash("Pending approval", "warning")
                return redirect(url_for("login"))
            session.clear()
            session["user_id"] = user.id
            return redirect(url_for("index"))
        flash("Invalid login", "danger")
    return """<h2>Login</h2><form method="post">
              <input name="username"><br>
              <input type="password" name="password"><br>
              <button>Login</button></form>"""

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")
        if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
            session.clear()
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Invalid admin login", "danger")
    return """<h2>Admin Login</h2><form method="post">
              <input name="username"><br>
              <input type="password" name="password"><br>
              <button>Login</button></form>"""

@app.route("/admin")
@admin_required
def admin_dashboard():
    pending = User.query.filter_by(approved=False).all()
    users = User.query.all()
    html = "<h2>Admin Dashboard</h2><h3>Pending</h3><ul>"
    for p in pending:
        html += f"<li>{p.username} <a href='/admin/approve/{p.id}'>Approve</a></li>"
    html += "</ul><h3>Users</h3><ul>"
    for u in users:
        html += f"<li>{u.username} - Approved: {u.approved}</li>"
    html += "</ul><a href='/logout'>Logout</a>"
    return html

@app.route("/admin/approve/<int:uid>")
@admin_required
def approve_user(uid):
    u = User.query.get_or_404(uid)
    u.approved = True
    db.session.commit()
    return redirect(url_for("admin_dashboard"))

# -----------------------
# INIT
# -----------------------
@app.before_first_request
def init_db():
    db.create_all()

# -----------------------
# ENTRYPOINT
# -----------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
