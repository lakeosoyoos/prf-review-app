"""PRF Review — local Flask backend for the desktop app. Offline only.

Serves the guided UI and runs the deterministic review pipeline in a background thread so the UI can
show live progress. No network calls; no LLM. Reads accounts (folders with account_config.yaml) from
the configured accounts root(s).
"""
import os, sys, json, threading, traceback, subprocess, platform
from flask import Flask, request, jsonify, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import pipeline

# When frozen (PyInstaller), HERE is a temp extraction dir; settings + accounts live beside the EXE.
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else HERE
WEB = os.path.join(HERE, "web")
SETTINGS = os.path.join(APP_DIR, "settings.json")


def accounts_roots():
    if os.path.exists(SETTINGS):
        try:
            r = (json.load(open(SETTINGS)) or {}).get("accounts_roots")
            if r:
                return [os.path.expanduser(p) for p in r]
        except Exception:
            pass
    # defaults: an 'accounts' folder beside the app, plus the user's Documents
    return [os.path.join(APP_DIR, "accounts"), os.path.expanduser("~/Documents")]


app = Flask(__name__, static_folder=None)
JOBS = {}   # job_id -> {progress:[...], done:bool, error:str|None, result:dict|None}


@app.route("/health")
def health():
    # Boot self-test endpoint (CI Gate 4). 200 == the frozen app actually came up.
    return ("ok", 200, {"Content-Type": "text/plain"})


@app.route("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.route("/web/<path:p>")
def web(p):
    return send_from_directory(WEB, p)


@app.route("/api/accounts")
def api_accounts():
    try:
        return jsonify({"accounts": pipeline.list_accounts(accounts_roots())})
    except Exception as e:
        return jsonify({"accounts": [], "error": str(e)})


@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(force=True)
    cfg = data.get("config_path"); mode = data.get("mode"); level = data.get("level")
    if not cfg or not os.path.exists(cfg):
        return jsonify({"error": "account config not found"}), 400
    job_id = str(len(JOBS) + 1)
    JOBS[job_id] = {"progress": [], "done": False, "error": None, "result": None}

    def worker():
        # run the pipeline in an isolated SUBPROCESS (keeps CPU-bound PDF/workbook work off the
        # server's GIL — in-thread it starves under the dev server). Works frozen (re-invokes the
        # app exe with --pipeline) and in dev (python run_cli.py).
        # frozen: re-invoke the .exe with the --run-worker sentinel (sys.executable IS the .exe);
        # dev: run the worker script with the python interpreter.
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--run-worker", cfg, mode or "", level or ""]
        else:
            cmd = [sys.executable, "-u", os.path.join(HERE, "run_cli.py"), cfg, mode or "", level or ""]
        try:
            # discard stderr (library warnings on scanned PDFs would otherwise fill the pipe and
            # deadlock the child); the worker reports real errors as JSON on stdout.
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=HERE)
            for line in p.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue                              # ignore any non-JSON noise
                if "progress" in msg:
                    JOBS[job_id]["progress"].append(msg["progress"])
                elif "result" in msg:
                    JOBS[job_id]["result"] = msg["result"]
                elif "error" in msg:
                    JOBS[job_id]["error"] = msg["error"]
                    JOBS[job_id]["progress"].append("ERROR: " + msg["error"])
            p.wait()
            if p.returncode and not JOBS[job_id]["result"] and not JOBS[job_id]["error"]:
                JOBS[job_id]["error"] = "the review did not finish (unexpected exit)"
        except Exception as e:
            JOBS[job_id]["error"] = str(e); traceback.print_exc()
        finally:
            JOBS[job_id]["done"] = True

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id):
    return jsonify(JOBS.get(job_id, {"error": "unknown job"}))


@app.route("/api/open-folder", methods=["POST"])
def api_open_folder():
    path = (request.get_json(force=True) or {}).get("path")
    if not path or not os.path.isdir(path):
        return jsonify({"error": "folder not found"}), 400
    try:
        s = platform.system()
        if s == "Windows":
            os.startfile(path)                       # noqa
        elif s == "Darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def run(host="127.0.0.1", port=5000, debug=False):
    app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    run(port=int(os.environ.get("PORT", "5000")), debug=False)
