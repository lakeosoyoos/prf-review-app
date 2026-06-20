import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def pytest_configure(config):
    config.addinivalue_line("markers", "boot: launches the built .exe (post-build, CI Gate 4)")
