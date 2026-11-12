#!/bin/zsh
set -e
cd "$(dirname "$0")"
echo "Unit tests"
(cd BE && python3 -m unittest discover -s tests -t . -q)
echo "UI tests (chromium + webkit)"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest e2e/test_ui.py -q
echo "All good."
