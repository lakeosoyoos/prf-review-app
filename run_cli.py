"""Pipeline runner invoked as a SUBPROCESS by the app (keeps the heavy CPU-bound PDF/workbook work
off the Flask server's GIL). Emits ONLY clean JSON, one object per line, on the REAL stdout:
  {"progress": "..."}   progress updates
  {"result": {...}}     final result
  {"error": "..."}      failure
The vendored scripts' own print() output is redirected to devnull so it can't corrupt the stream.
Usage: python run_cli.py <config_path> <mode> <level>   (mode/level may be empty strings)
"""
import os, sys, json, contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_REAL_OUT = sys.stdout   # keep a handle to the real stdout for clean JSON, even while we silence prints


def _emit(obj):
    _REAL_OUT.write(json.dumps(obj) + "\n")
    _REAL_OUT.flush()


def run(config_path, mode, level):
    from core import pipeline
    def prog(m):
        _emit({"progress": m})
    devnull = open(os.devnull, "w")
    try:
        with contextlib.redirect_stdout(devnull):          # silence the vendored scripts' chatter
            res = pipeline.run_review(config_path, mode=mode or None, level=level or None, progress=prog)
        _emit({"result": res})
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        _emit({"error": str(e)})
    finally:
        devnull.close()


if __name__ == "__main__":
    a = sys.argv[1:]
    run(a[0], a[1] if len(a) > 1 else "", a[2] if len(a) > 2 else "")
