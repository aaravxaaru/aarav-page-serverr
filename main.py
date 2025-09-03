"""
Safe Demo: FB Auto Comment Tool (Simulation)
- Multiple tokens via uploaded file (one token per line)
- Comments via uploaded .txt (one per line)
- Prefix/Name field added to each comment
- Background worker simulates sending by writing "prepared requests" to a log file
- Start / Stop tasks, Status endpoint, Logs & Export

Run:
  pip install -r requirements.txt
  python main.py
Open: http://127.0.0.1:5000
"""
import os
import time
import json
import datetime
from threading import Thread, Event
from flask import Flask, request, render_template_string, send_file, jsonify, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

# tasks store: task_id -> { thread, stop_event, meta, logs_file }
tasks = {}
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# HTML template (kept styling like your preferred white UI)
INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FB Auto Comment Tool by Aarav Shrivastava (Demo)</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background-color: white; color: black; }
    .container { max-width: 420px; min-height: 600px; border-radius: 20px; padding: 20px; box-shadow: 0 0 15px gray; margin-bottom: 20px; }
    .form-control { border: 1px solid black; background: #f9f9f9; height: 40px; padding: 7px; margin-bottom: 12px; border-radius: 10px; color: black; }
    textarea.form-control { height: 90px; }
    .header { text-align: center; padding-bottom: 20px; }
    .btn-submit { width: 100%; margin-top: 10px; }
    .muted { font-size: 0.9rem; color: #555; }
    .small-note { font-size: 0.85rem; color: #666; margin-top:8px; }
  </style>
</head>
<body>
  <header class="header mt-4">
    <h3 class="mt-2">FB Auto Comment Tool by Aarav Shrivastava</h3>
    
  </header>

  <div class="container text-center">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for cat, msg in messages %}
          <div class="alert alert-{{cat}}">{{msg}}</div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <form method="post" enctype="multipart/form-data">
      <div class="mb-2 text-start">
        <label class="form-label">Upload Token File (one token per line)</label>
        <input type="file" name="tokenFile" class="form-control" required>
      </div>

      <div class="mb-2 text-start">
        <label class="form-label">Post ID</label>
        <input type="text" name="postId" class="form-control" placeholder="12345678903372_261818157518581" required>
      </div>

      <div class="mb-2 text-start">
        <label class="form-label">Prefix / Name</label>
        <input type="text" name="prefix" class="form-control" ,placeholder="<<AARAV DON HERE(Y)>>  HATERS  RKB " required>
      </div>

      <div class="mb-2 text-start">
        <label class="form-label">Time Delay (seconds)</label>
        <input type="number" name="time" class="form-control" value="240" min="1" required>
      </div>

      <div class="mb-2 text-start">
        <label class="form-label">Comments File (.txt) — one per line</label>
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

    <div class="mt-3">
    
    </div>
  </div>
    <footer class="text-center mt-4 mb-3" style="font-size:0.9rem; color:#555;">
    <hr>
    <p>Developed by <strong>Aarav Shrivastava</strong> | WhatsApp: 
      <a href="https://wa.me/918809497526" target="_blank">+91 8809497526</a>
    </p>
    <p>© All Rights Reserved</p>
    <p>© 2022 - 2025  Aarav. All Rights Reserved.</p>
  </footer>

</body>
</html>
"""

# Worker (simulation) - does NOT send real HTTP requests to Facebook
def worker_simulate(task_id, tokens, post_id, prefix, interval, comments):
    """
    Loop until stop_event is set. For each iteration:
       - pick comment and token (round-robin)
       - prepare payload dict
       - append payload JSON to log file for this task
    """
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
                "token_preview": token_used[:8] + "...",  # do not expose full tokens in UI logs
                "prefix": prefix,
                "message": f"{prefix} {msg_text}",
                "simulated_status": "queued"  # possible values: queued/simulated_sent/failure
            }

            # write to log file (append JSON line)
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(json.dumps(prepared, ensure_ascii=False) + "\n")

            # also keep small in-memory recent list
            meta["recent"].append(prepared)
            if len(meta["recent"]) > 200:
                meta["recent"].pop(0)

            run_count += 1
            idx_comment = (idx_comment + 1) % len(comments)
            idx_token = (idx_token + 1) % len(tokens)

            # for demo clarity, mark simulated_status as 'simulated_sent' after a few runs
            if run_count % 5 == 0:
                prepared["simulated_status"] = "simulated_sent"

        except Exception as e:
            # log the error into the same file as an entry
            err = {
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "error": str(e)
            }
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(json.dumps(err, ensure_ascii=False) + "\n")

        # sleep respecting interval (but clamp a minimum of 1 second)
        try:
            time.sleep(max(1, float(interval)))
        except:
            time.sleep(1)

# Routes
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # token file required
        token_file = request.files.get("tokenFile")
        if not token_file or not token_file.filename:
            flash("Token file is required (one token per line)", "danger")
            return redirect(url_for("index"))
        tokens_raw = token_file.read().decode("utf-8", errors="ignore").strip().splitlines()
        tokens = [t.strip() for t in tokens_raw if t.strip()]
        if not tokens:
            flash("No tokens found in uploaded file", "danger")
            return redirect(url_for("index"))

        post_id = request.form.get("postId", "").strip()
        prefix = request.form.get("prefix", "").strip()
        try:
            interval = float(request.form.get("time", "10"))
        except:
            interval = 10.0

        txtfile = request.files.get("txtFile")
        if not txtfile or not txtfile.filename:
            flash("Comments file is required", "danger")
            return redirect(url_for("index"))
        comments_raw = txtfile.read().decode("utf-8", errors="ignore").splitlines()
        comments = [c.strip() for c in comments_raw if c.strip()]
        if not comments:
            flash("Comments file is empty", "danger")
            return redirect(url_for("index"))

        # create task id and log file
        task_id = os.urandom(4).hex()
        log_file = os.path.join(LOG_DIR, f"{task_id}.log")

        stop_ev = Event()
        tasks[task_id] = {
            "thread": None,
            "stop": stop_ev,
            "meta": {
                "post_id": post_id,
                "prefix": prefix,
                "interval": interval,
                "tokens_count": len(tokens),
                "comments_count": len(comments),
                "created_at": datetime.datetime.utcnow().isoformat() + "Z"
            },
            "log_file": log_file,
            "recent": []
        }

        t = Thread(target=worker_simulate, args=(task_id, tokens, post_id, prefix, interval, comments))
        t.daemon = True
        tasks[task_id]["thread"] = t
        t.start()

        flash(f"Demo task started. Task ID: {task_id}", "success")
        return redirect(url_for("index"))

    return render_template_string(INDEX_HTML)

@app.route("/stop", methods=["POST"])
def stop_task():
    tid = request.form.get("taskId", "").strip()
    if not tid:
        flash("Please provide a Task ID", "danger")
        return redirect(url_for("index"))
    entry = tasks.get(tid)
    if not entry:
        flash(f"No such task: {tid}", "danger")
        return redirect(url_for("index"))
    entry["stop"].set()
    flash(f"Task {tid} stopped.", "success")
    return redirect(url_for("index"))

@app.route("/status")
def status():
    out = {}
    for tid, rec in tasks.items():
        th = rec.get("thread")
        out[tid] = {
            "alive": (th.is_alive() if th else False),
            "meta": rec.get("meta", {}),
            "log_file": rec.get("log_file")
        }
    return jsonify(out)

@app.route("/tasks")
def tasks_page():
    # Simple listing of tasks and quick links to logs
    rows = []
    for tid, rec in tasks.items():
        th = rec.get("thread")
        rows.append({
            "task_id": tid,
            "alive": (th.is_alive() if th else False),
            "meta": rec.get("meta", {}),
            "log_file": rec.get("log_file")
        })
    # render a small HTML snippet
    rows_html = "<ul>"
    for r in rows:
        rows_html += f"<li><strong>{r['task_id']}</strong> - alive: {r['alive']} - tokens: {r['meta'].get('tokens_count')} - comments: {r['meta'].get('comments_count')} "
        rows_html += f" - <a href='/logs/{r['task_id']}'>View Logs</a> - <a href='/download/{r['task_id']}'>Download</a></li>"
    rows_html += "</ul>"
    return f"<html><body><h3>Tasks</h3>{rows_html}<p><a href='/'>Back</a></p></body></html>"

@app.route("/logs/<task_id>")
def view_logs(task_id):
    rec = tasks.get(task_id)
    if not rec:
        return "No such task", 404
    # show recent prepared items in-memory and tail of file
    recent = rec.get("recent", [])[-50:]
    tail_lines = []
    # read last ~200 lines from log file if exists
    try:
        with open(rec["log_file"], "r", encoding="utf-8") as lf:
            lines = lf.readlines()[-200:]
            tail_lines = [l.strip() for l in lines if l.strip()]
    except FileNotFoundError:
        tail_lines = []
    html = "<h3>Recent (in-memory)</h3><pre>{}</pre><h3>Log file tail</h3><pre>{}</pre><p><a href='/tasks'>Back</a></p>".format(
        json.dumps(recent, indent=2, ensure_ascii=False),
        "\n".join(tail_lines)
    )
    return html

@app.route("/download/<task_id>")
def download_log(task_id):
    rec = tasks.get(task_id)
    if not rec:
        return "No such task", 404
    lf = rec.get("log_file")
    if not os.path.exists(lf):
        return "Log file not found", 404
    return send_file(lf, as_attachment=True, download_name=f"{task_id}.log")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
