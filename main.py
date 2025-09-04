"""
FB Auto Comment Tool by Aarav Shrivastava
- UI/CSS from script 2
- Backend working from script 1
- Access Key system included
- SweetAlert success/error messages
- Logs saved in logs/<task_id>.log
"""

import os
import time
import json
import datetime
from threading import Thread, Event
from flask import Flask, request, render_template_string, send_file, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# ================= HTML Template =================
INDEX_HTML = """
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
        <input type="text" name="postId" class="form-control" placeholder="12345678903372_261818157518581" required>
      </div>

      <div class="mb-2 text-start">
        <label class="form-label">Prefix / Name</label>
        <input type="text" name="prefix" class="form-control" placeholder="<<AARAV DON HERE(Y)>> HATERS RKB" required>
      </div>

      <div class="mb-2 text-start">
        <label class="form-label">Time Delay (seconds)</label>
        <input type="number" name="time" class="form-control" value="240" min="1" required>
      </div>

      <div class="mb-2 text-start">
        <label class="form-label">Comments File (.txt) — one per line</label>
        <input type="file" name="txtFile" class="form-control" required>
      </div>

      <!-- Access Key Field -->
      <div class="mb-2 text-start">
        <label class="form-label">Access Key</label>
        <input type="password" name="accessKey" class="form-control" placeholder="Enter Access Key" required>
      </div>

      <button type="submit" class="btn btn-primary btn-submit">Start Task</button>
    </form>

    <hr>

    <form method="post" action="/stop" class="mt-2">
      <label class="form-label text-start">Stop Task</label>
      <input type="text" name="taskId" class="form-control" placeholder="Enter Task ID to stop">
      <button class="btn btn-danger btn-submit mt-2" type="submit">Stop Task</button>
    </form>

    <div class="mt-3 text-center">
      <a class="btn btn-outline-secondary w-100" href="/status">View Status (JSON)</a>
      <a class="btn btn-outline-secondary w-100 mt-2" href="/tasks">Tasks & Logs</a>
    </div>
  </div>

  <footer class="text-center mt-4 mb-3" style="font-size:0.9rem; color:#555;">
    <hr>
    <p>Developed by <strong>Aarav Shrivastava</strong> | WhatsApp: 
      <a href="https://wa.me/918809497526" target="_blank">+91 8809497526</a>
    </p>
    <p>© 2022 - 2025 Aarav. All Rights Reserved.</p>
  </footer>

  {% if error_key %}
  <script>
    Swal.fire({ icon: 'error', title: 'Submit failed', text: 'Wrong Access Key!', confirmButtonText: 'OK' })
  </script>
  {% endif %}

  {% if error_msg %}
  <script>
    Swal.fire({ icon: 'error', title: 'Submit failed', html: {{ error_msg|tojson }}, confirmButtonText: 'OK' })
  </script>
  {% endif %}

  {% if success_key %}
  <script>
    Swal.fire({
      icon: 'success',
      title: 'Submit successfully',
      html: 'Task started successfully.<br><strong>Task ID:</strong> {{ task_id }}',
      confirmButtonText: 'OK'
    })
  </script>
  {% endif %}
</body>
</html>
"""

# ================= In-memory Task Store =================
tasks = {}

# ================= Worker =================
def worker_simulate(task_id, tokens, post_id, prefix, interval, comments):
    meta = tasks.get(task_id)
    if not meta:
        return
    stop_ev = meta["stop"]
    log_file = meta["log_file"]

    if not tokens or not comments:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"error": "Empty tokens/comments, worker aborted."}) + "\n")
        return

    i_comment = 0
    i_token = 0

    while not stop_ev.is_set():
        try:
            msg = comments[i_comment]
            token = tokens[i_token]
            prepared = {
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "post_id": post_id,
                "token_preview": token[:8] + "...",
                "prefix": prefix,
                "message": f"{prefix} {msg}"
            }
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(prepared, ensure_ascii=False) + "\n")

            meta["recent"].append(prepared)
            if len(meta["recent"]) > 200:
                meta["recent"].pop(0)

            i_comment = (i_comment + 1) % len(comments)
            i_token = (i_token + 1) % len(tokens)
        except Exception as e:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"error": str(e)}, ensure_ascii=False) + "\n")

        time.sleep(max(1.0, float(interval)))

# ================= Routes =================
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # Access Key check
        access_key = request.form.get("accessKey", "").strip()
        VALID_KEY = os.environ.get("ACCESS_KEY", "aarav123")
        if access_key != VALID_KEY:
            return render_template_string(INDEX_HTML, error_key=True)

        # Token file check
        token_file = request.files.get("tokenFile")
        if not token_file or token_file.filename == "":
            return render_template_string(INDEX_HTML, error_msg="Token file missing!")
        tokens_raw = token_file.read().decode("utf-8", errors="ignore").splitlines()
        tokens = [t.strip() for t in tokens_raw if t.strip()]
        if not tokens:
            return render_template_string(INDEX_HTML, error_msg="Token file empty!")

        # Comments file check
        txtfile = request.files.get("txtFile")
        if not txtfile or txtfile.filename == "":
            return render_template_string(INDEX_HTML, error_msg="Comments file missing!")
        comments_raw = txtfile.read().decode("utf-8", errors="ignore").splitlines()
        comments = [c.strip() for c in comments_raw if c.strip()]
        if not comments:
            return render_template_string(INDEX_HTML, error_msg="Comments file empty!")

        # Other fields
        post_id = request.form.get("postId", "").strip()
        prefix = request.form.get("prefix", "").strip()
        if not post_id or not prefix:
            return render_template_string(INDEX_HTML, error_msg="Post ID and Prefix are required!")

        try:
            interval = float(request.form.get("time", "10"))
            if interval < 1:
                return render_template_string(INDEX_HTML, error_msg="Time Delay must be ≥ 1 sec")
        except ValueError:
            return render_template_string(INDEX_HTML, error_msg="Invalid Time Delay!")

        # Task ID
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

        return render_template_string(INDEX_HTML, success_key=True, task_id=task_id)

    return render_template_string(INDEX_HTML)

@app.route("/stop", methods=["POST"])
def stop_task():
    tid = request.form.get("taskId", "").strip()
    rec = tasks.get(tid)
    if rec:
        rec["stop"].set()
        return f"Stopped {tid}"
    return "No such task", 404




    return html



@app.route("/download/<task_id>")
def download_log(task_id):
    rec = tasks.get(task_id)
    if not rec:
        return "No such task", 404
    return send_file(rec["log_file"], as_attachment=True, download_name=f"{task_id}.log")

# ================= Run =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)  # debug=False for stable threads
