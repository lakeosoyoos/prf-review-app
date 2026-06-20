"""Frozen entry point for the PRF Review desktop app.

Order of operations matters when frozen (sys.executable IS the .exe):
  1. argv sentinel `--run-worker` is dispatched FIRST — before Flask/anything boots — because the
     app re-invokes itself as the review worker (see app.py /api/run). If we booted the server first,
     every worker invocation would also spin up a server.
  2. `--server-only` runs the Flask server headless on a known PORT and prints a READY line — this is
     what the CI BOOT SELF-TEST (Gate 4) launches and polls at /health.
  3. default: run the server on a free port and open the browser (robust; no native WebView needed).
     pywebview, if installed, is used for a native window — but it's a GUARDED optional import so a
     missing/broken WebView can never stop the app from launching.

APP_HOME is exported so bundled assets resolve from the extraction root in both frozen and dev runs.
"""
import os, sys, time, socket, threading, webbrowser

# ----- bundle root / APP_HOME -----------------------------------------------------------------
if getattr(sys, "frozen", False):
    APP_HOME = sys._MEIPASS                      # PyInstaller extraction dir
    EXE_DIR = os.path.dirname(sys.executable)    # where the .exe / settings.json / accounts live
else:
    APP_HOME = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR = APP_HOME
os.environ.setdefault("APP_HOME", APP_HOME)
sys.path.insert(0, APP_HOME)


def _dispatch_worker():
    """If invoked as the review worker, run it and exit (must happen before the server boots)."""
    if len(sys.argv) > 1 and sys.argv[1] == "--run-worker":
        import run_cli
        a = sys.argv[2:]
        run_cli.run(a[0], a[1] if len(a) > 1 else "", a[2] if len(a) > 2 else "")
        return True
    return False


def _free_port(start=0):
    if start:
        for p in range(start, start + 50):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", p)) != 0:
                    return p
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_up(port, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


def main():
    if _dispatch_worker():
        return

    import app as backend

    server_only = ("--server-only" in sys.argv) or os.environ.get("PRF_SERVER_ONLY") == "1"
    port = int(os.environ.get("PORT") or (8765 if server_only else _free_port()))

    threading.Thread(target=lambda: backend.run(port=port), daemon=True).start()
    up = _wait_up(port, timeout=30)
    url = f"http://127.0.0.1:{port}/"

    if server_only:
        # Headless mode for the CI boot self-test (and for debugging). Print a parseable READY line.
        print(f"READY {url}" if up else "FAILED server did not bind", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return

    # Normal launch: native window if pywebview is available (guarded), else the default browser.
    if os.environ.get("PRF_NO_WINDOW") != "1":
        try:
            import webview
            webview.create_window("PRF High Dollar Review", url, width=1040, height=760, min_size=(820, 600))
            webview.start()
            return
        except Exception:
            pass
    webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
