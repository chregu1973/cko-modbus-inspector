#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
python -m pip install --disable-pip-version-check -q -r requirements.txt
python app.py

