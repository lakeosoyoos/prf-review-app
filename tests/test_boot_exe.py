"""Gate 4 — BOOT SELF-TEST (the single most important gate).

Launch the actually-built executable in --server-only mode and poll its /health endpoint for up to
90s. If it doesn't come up healthy, FAIL — a build that compiled but crashes on launch must NOT
proceed to the installer/publish. On failure, the captured stdout/stderr is printed for debugging.

Marked `boot` so it's excluded from the pre-build pytest run and invoked only AFTER the build:
    pytest -m boot
Set PRF_EXE to the built binary path (the CI workflow does this); otherwise the test self-discovers
dist/PRF Review[.exe] and skips if absent (so a dev `pytest` doesn't fail without a build).
"""
import os, sys, time, glob, subprocess
import pytest
import urllib.request

PORT = int(os.environ.get("PRF_BOOT_PORT", "8765"))
TIMEOUT = int(os.environ.get("PRF_BOOT_TIMEOUT", "90"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_exe():
    env = os.environ.get("PRF_EXE")
    if env and os.path.exists(env):
        return env
    pats = ["dist/PRF Review.exe", "dist/PRF Review", "dist/PRF Review.app/Contents/MacOS/PRF Review"]
    for p in pats:
        hits = glob.glob(os.path.join(ROOT, p))
        if hits:
            return hits[0]
    return None


@pytest.mark.boot
def test_built_exe_boots_and_is_healthy():
    exe = _find_exe()
    if not exe:
        pytest.skip("no built executable found (run the PyInstaller build first)")

    env = dict(os.environ, PRF_SERVER_ONLY="1", PORT=str(PORT))
    proc = subprocess.Popen([exe, "--server-only"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        url = f"http://127.0.0.1:{PORT}/health"
        deadline = time.time() + TIMEOUT
        healthy = False
        while time.time() < deadline:
            if proc.poll() is not None:                # process died early
                break
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200 and r.read().decode().strip() == "ok":
                        healthy = True
                        break
            except Exception:
                time.sleep(1)
        if not healthy:
            try:
                proc.terminate(); out = proc.communicate(timeout=10)[0]
            except Exception:
                out = "(could not capture output)"
            pytest.fail(f"BOOT SELF-TEST FAILED: '{exe}' did not become healthy at {url} within "
                        f"{TIMEOUT}s.\n----- exe output -----\n{out}")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
