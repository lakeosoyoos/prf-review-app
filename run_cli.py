"""Pipeline runner invoked as a SUBPROCESS by the app (keeps the heavy CPU-bound PDF/workbook work
off the Flask server's GIL). Emits one JSON object per line:
  {"progress": "..."}   progress updates
  {"result": {...}}     final result
  {"error": "..."}      failure

Output sink: a PROGRESS FILE path (4th arg) when provided — required for the frozen WINDOWED exe,
where sys.stdout is None and stdout-based IPC is impossible. Falls back to stdout in dev.
The vendored scripts' own print() output is redirected to devnull so it can't corrupt the stream.

Usage: python run_cli.py <config_path> <mode> <level> [progress_file]
"""
import os, sys, json, contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def run(config_path, mode, level, progress_path=None):
    from core import pipeline
    sink = open(progress_path, "a", encoding="utf-8") if progress_path else None

    def emit(obj):
        line = json.dumps(obj) + "\n"
        if sink:
            sink.write(line); sink.flush()
        else:
            try:
                sys.__stdout__.write(line); sys.__stdout__.flush()
            except Exception:
                pass

    def prog(m):
        emit({"progress": m})

    devnull = open(os.devnull, "w")
    try:
        with contextlib.redirect_stdout(devnull):       # silence the vendored scripts' chatter
            res = pipeline.run_review(config_path, mode=mode or None, level=level or None, progress=prog)
        emit({"result": res})
    except Exception as e:
        emit({"error": str(e)})
    finally:
        devnull.close()
        if sink:
            sink.close()


if __name__ == "__main__":
    a = sys.argv[1:]
    run(a[0], a[1] if len(a) > 1 else "", a[2] if len(a) > 2 else "", a[3] if len(a) > 3 else None)
