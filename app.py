"""PRF Review — local Flask backend for the desktop app. Offline only.

Serves the guided UI and runs the deterministic review pipeline in a background thread so the UI can
show live progress. No network calls; no LLM. Reads accounts (folders with account_config.yaml) from
the configured accounts root(s).
"""
import os, sys, json, time, tempfile, threading, traceback, subprocess, platform
from flask import Flask, request, jsonify, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import pipeline

# When frozen (PyInstaller), HERE is a temp extraction dir; settings + accounts live beside the EXE.
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else HERE
WEB = os.path.join(HERE, "web")
SETTINGS = os.path.join(APP_DIR, "settings.json")


def _bridge_settings_to_env():
    """Let settings.json configure the local handwriting model without a terminal. Sets the
    PRF_LOCAL_VLM_* env vars (only if not already set) so the review subprocess inherits them."""
    if not os.path.exists(SETTINGS):
        return
    try:
        cfg = json.load(open(SETTINGS)) or {}
    except Exception:
        return
    for key, env in (("vlm_model", "PRF_LOCAL_VLM_MODEL"),
                     ("vlm_url", "PRF_LOCAL_VLM_URL"),
                     ("vlm_trusted_host", "PRF_LOCAL_VLM_TRUSTED_HOST")):
        val = cfg.get(key)
        if val and not os.environ.get(env):
            os.environ[env] = str(val)


_bridge_settings_to_env()


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


def app_version():
    """Build stamp written by CI into version.txt (bundled). 'dev' when run from source."""
    base = getattr(sys, "_MEIPASS", HERE)
    for p in (os.path.join(base, "version.txt"), os.path.join(HERE, "version.txt")):
        try:
            v = open(p).read().strip()
            if v:
                return v
        except OSError:
            continue
    return "dev"


@app.route("/health")
def health():
    # Boot self-test endpoint (CI Gate 4). 200 == the frozen app actually came up.
    return ("ok", 200, {"Content-Type": "text/plain"})


@app.route("/api/version")
def api_version():
    return jsonify({"version": app_version()})


@app.route("/api/reader-status")
def api_reader_status():
    # what offline document-reading is available on this machine (no network)
    try:
        from core.extract import ingest
        return jsonify(ingest.reader_status())
    except Exception as e:
        return jsonify({"parsers": False, "error": str(e)})


@app.route("/api/vlm-test")
def api_vlm_test():
    # probe the local handwriting model (loopback / trusted on-prem host only)
    try:
        from core.extract import local_extract
        return jsonify(local_extract.vlm_status())
    except Exception as e:
        return jsonify({"reachable": False, "error": str(e)})


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
        # Run the pipeline in an isolated SUBPROCESS (keeps CPU-bound PDF work off the server GIL).
        # IPC is via a PROGRESS FILE — required because the frozen WINDOWED exe has no stdout.
        # frozen: re-invoke the .exe with --run-worker (sys.executable IS the .exe); dev: run the script.
        prog_fd, prog_path = tempfile.mkstemp(suffix=".jsonl")
        os.close(prog_fd)
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--run-worker", cfg, mode or "", level or "", prog_path]
        else:
            cmd = [sys.executable, "-u", os.path.join(HERE, "run_cli.py"), cfg, mode or "", level or "", prog_path]
        popen_kw = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=HERE)
        if os.name == "nt":
            popen_kw["creationflags"] = 0x08000000        # CREATE_NO_WINDOW — no console flash
        pos = 0

        def drain():
            nonlocal pos
            try:
                with open(prog_path, encoding="utf-8") as f:
                    f.seek(pos); chunk = f.read(); pos = f.tell()
            except FileNotFoundError:
                return
            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if "progress" in msg:
                    JOBS[job_id]["progress"].append(msg["progress"])
                elif "result" in msg:
                    JOBS[job_id]["result"] = msg["result"]
                elif "error" in msg:
                    JOBS[job_id]["error"] = msg["error"]
                    JOBS[job_id]["progress"].append("ERROR: " + msg["error"])

        try:
            p = subprocess.Popen(cmd, **popen_kw)
            while p.poll() is None:
                drain(); time.sleep(0.3)
            drain()                                       # final flush
            if p.returncode and not JOBS[job_id]["result"] and not JOBS[job_id]["error"]:
                JOBS[job_id]["error"] = "the review did not finish (unexpected exit)"
        except Exception as e:
            JOBS[job_id]["error"] = str(e); traceback.print_exc()
        finally:
            try:
                os.remove(prog_path)
            except OSError:
                pass
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
