import os
import time
import json
import datetime
from threading import Thread, Event
from flask import Flask, request, render_template_string, send_file, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

# -----------------------
# APP CONFIG
# -----------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "users.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Admin credentials
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
# HELPERS
# -----------------------
def login_required(f):
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        user = User.query.get(session["user_id"])
        if not user or not user.approved:
            session.clear()
            flash("Your account is not approved yet.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def admin_required(f):
    def wrapper(*args, **kwargs):
        if session.get("is_admin") != True:
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# -----------------------
# OLD INDEX PAGE (protected)
# -----------------------
INDEX_HTML = """  <!-- (same HTML as your old script, unchanged) -->
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FB Auto Comment Tool by Aarav Shrivastava</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
  <style>
    body { background-color: white; color: black; }
    .container { max-width: 420px; min-height: 600px; border-radius: 20px; padding: 20px; box-shadow: 0 0 15px gray; margin-bottom: 20px; }
    .form-control { border: 1px solid black; background: #f9f9f9; height: 40px; padding: 7px; margin-bottom: 12px; border-radius: 10px; color: black; }
    textarea.form-control { height: 90px; }
    .header { text-align: center; padding-bottom: 20px; }
    .btn-submit { width: 100%; margin-top: 10px; }
  </style>
</head>
<body>
  <header class="header mt-4">
    <h3 class="mt-2">FB Auto Comment Tool by Aarav Shrivastava</h3>
  </header>

  <div class="container text-center">
    <form method="post" enctype="multipart/form-data">
      <div class="mb-2 text-start">
        <label class="form-label">Upload Token File (one token per line)</label>
        <input type="file" name="tokenFile" class="form-control" required>
      </div>

      <div class="mb-2 text-start">
        <label class="form-label">Post ID</label>
        <input type="text" name="postId" class="form-control" required>
      </div>

      <div class="mb-2 text-start">
        <label class="form-label">Prefix / Name</label>
        <input type="text" name="prefix" class="form-control" required>
      </div>

      <div class="mb-2 text-start">
        <label class="form-label">Time Delay (seconds)</label>
        <input type="number" name="time" class="form-control" value="240" min="1" required>
      </div>

      <div class="mb-2 text-start">
        <label class="form-label">Comments File (.txt)</label>
        <input type="file" name="txtFile" class="form-control" required>
      </div>

      <button class="btn btn-primary btn-submit">Start Demo Task</button>
    </form>

    <hr>
    <form method="post" action="/stop" class="mt-2">
      <label class="form-label text-start">Stop Task</label>
      <input type="text" name="taskId" class="form-control" placeholder="Enter Task ID to stop">
      <button class="btn btn-danger btn-submit mt-2">Stop Task</button>
    </form>
  </div>

  <footer class="text-center mt-4 mb-3" style="font-size:0.9rem; color:#555;">
    <hr>
    <p>Developed by <strong>Aarav Shrivastava</strong></p>
  </footer>
</body>
</html>
"""

# -----------------------
# BACKGROUND WORKER
# -----------------------
def worker_simulate(task_id, tokens, post_id, prefix, interval, comments):
    meta = tasks.get(task_id)
    if not meta:
        return
    stop_event = meta["stop"]
    log_path = meta["log_file"]

    idx_comment = 0
    idx_token = 0
    run_count = 0

    while not stop_event.is_set():
        try:
            msg_text = comments[idx_comment]
            token_used = tokens[idx_token]

            prepared = {
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "post_id": post_id,
                "token_preview": token_used[:8] + "...",
                "prefix": prefix,
                "message": f"{prefix} {msg_text}",
                "status": "simulated"
            }

            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(json.dumps(prepared, ensure_ascii=False) + "\n")

            meta["recent"].append(prepared)
            if len(meta["recent"]) > 200:
                meta["recent"].pop(0)

            run_count += 1
            idx_comment = (idx_comment + 1) % len(comments)
            idx_token = (idx_token + 1) % len(tokens)

        except Exception as e:
            err = {"timestamp": datetime.datetime.utcnow().isoformat() + "Z", "error": str(e)}
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(json.dumps(err, ensure_ascii=False) + "\n")

        time.sleep(max(1, float(interval)))

# -----------------------
# ROUTES
# -----------------------

# Protected home
@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        token_file = request.files.get("tokenFile")
        if not token_file:
            flash("Token file is required", "danger")
            return redirect(url_for("index"))
        tokens = token_file.read().decode("utf-8").splitlines()
        post_id = request.form.get("postId")
        prefix = request.form.get("prefix")
        interval = float(request.form.get("time", 10))
        txtfile = request.files.get("txtFile")
        comments = txtfile.read().decode("utf-8").splitlines()

        task_id = os.urandom(4).hex()
        log_file = os.path.join(LOG_DIR, f"{task_id}.log")
        stop_ev = Event()
        tasks[task_id] = {"thread": None, "stop": stop_ev, "log_file": log_file, "recent": []}

        t = Thread(target=worker_simulate, args=(task_id, tokens, post_id, prefix, interval, comments))
        t.daemon = True
        tasks[task_id]["thread"] = t
        t.start()

        flash(f"Task started with ID {task_id}", "success")
    return render_template_string(INDEX_HTML)

@app.route("/stop", methods=["POST"])
@login_required
def stop_task():
    tid = request.form.get("taskId")
    if tid in tasks:
        tasks[tid]["stop"].set()
        flash(f"Task {tid} stopped.", "info")
    return redirect(url_for("index"))

# -----------------------
# AUTH ROUTES
# -----------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if User.query.filter_by(username=username).first():
            flash("Username already taken", "danger")
            return redirect(url_for("register"))
        u = User(username=username, password_hash=generate_password_hash(password), approved=False)
        db.session.add(u)
        db.session.commit()
        flash("Registered successfully. Wait for admin approval.", "info")
        return redirect(url_for("login"))
    return """<h2>Register</h2><form method="post">
        <input name="username"><br><input name="password" type="password"><br>
        <button type="submit">Register</button></form>"""

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        # admin login
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session.clear()
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        # user login
        u = User.query.filter_by(username=username).first()
        if u and u.check_password(password):
            if not u.approved:
                flash("Pending approval.", "warning")
                return redirect(url_for("login"))
            session.clear()
            session["user_id"] = u.id
            return redirect(url_for("index"))
        flash("Invalid credentials", "danger")
    return """<h2>Login</h2><form method="post">
        <input name="username"><br><input name="password" type="password"><br>
        <button type="submit">Login</button></form>"""

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -----------------------
# ADMIN ROUTES
# -----------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session.clear()
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Invalid admin login", "danger")
    return """<h2>Admin Login</h2><form method="post">
        <input name="username"><br><input name="password" type="password"><br>
        <button type="submit">Login</button></form>"""

@app.route("/admin")
@admin_required
def admin_dashboard():
    pending = User.query.filter_by(approved=False).all()
    users = User.query.order_by(User.created_at.desc()).all()
    html = "<h2>Admin Dashboard</h2>"
    html += "<h3>Pending Approvals</h3><ul>"
    for p in pending:
        html += f"<li>{p.username} <a href='/admin/approve/{p.id}'>Approve</a> | <a href='/admin/reject/{p.id}'>Reject</a></li>"
    html += "</ul><h3>All Users</h3><ul>"
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

@app.route("/admin/reject/<int:uid>")
@admin_required
def reject_user(uid):
    u = User.query.get_or_404(uid)
    db.session.delete(u)
    db.session.commit()
    return redirect(url_for("admin_dashboard"))

# -----------------------
# INIT
# -----------------------
@app.before_first_request
def init_db():
    db.create_all()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
