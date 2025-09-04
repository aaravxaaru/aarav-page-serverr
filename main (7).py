import os
import time
import json
import datetime
from threading import Thread, Event
from flask import Flask, request, render_template_string, send_file, jsonify, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

tasks = {}
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

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
    <p>Developed by <strong>Aarav Shrivastava</strong> | WhatsApp: 
      <a href="https://wa.me/918809497526" target="_blank">+91 8809497526</a>
    </p>
    <p>© All Rights Reserved</p>
    <p>© 2022 - 2025 Darkester. All Rights Reserved.</p>
  </footer>

  {% if error_key %}
  <script>
    Swal.fire({
      icon: 'error',
      title: 'Submit failed',
      text: 'Wrong Access Key!',
      confirmButtonText: 'OK'
    })
  </script>
  {% endif %}

  {% if success_key %}
  <script>
    Swal.fire({
      icon: 'success',
      title: 'Submit successfully',
      text: 'Task started successfully. Task ID: {{ task_id }}',
      confirmButtonText: 'OK'
    })
  </script>
  {% endif %}
</body>
</html>
"""

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
                "simulated_status": "queued"
            }

            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(json.dumps(prepared, ensure_ascii=False) + "\\n")

            meta["recent"].append(prepared)
            if len(meta["recent"]) > 200:
                meta["recent"].pop(0)

            run_count += 1
            idx_comment = (idx_comment + 1) % len(comments)
            idx_token = (idx_token + 1) % len(tokens)

            if run_count % 5 == 0:
                prepared["simulated_status"] = "simulated_sent"

        except Exception as e:
            err = {
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "error": str(e)
            }
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(json.dumps(err, ensure_ascii=False) + "\\n")

        try:
            time.sleep(max(1, float(interval)))
        except:
            time.sleep(1)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # Access Key check
        access_key = request.form.get("accessKey", "").strip()
        VALID_KEY = os.environ.get("ACCESS_KEY", "aarav123")
        if access_key != VALID_KEY:
            return render_template_string(INDEX_HTML, error_key=True)

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
