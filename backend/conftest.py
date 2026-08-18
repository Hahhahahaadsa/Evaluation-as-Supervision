import os
import sys

# Ensure the backend root (this file's directory) is importable as the project
# root, so `import app` and `import tests` work regardless of how pytest is
# launched (bare `pytest` vs `python -m pytest`).
sys.path.insert(0, os.path.dirname(__file__))
