#!/usr/bin/env sh
# City Infrastructure Designer – start it and open it in your web browser.
# Double-click this file (or run ./start-app.sh). Keep the window open while you work.
cd "$(dirname "$0")/backend" || exit 1
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
  echo "Python 3.11 or newer is needed. Install it from https://www.python.org/downloads/ and try again."
  exit 1
fi
if ! "$PY" -c "import yaml, numpy, scipy" 2>/dev/null; then
  echo "First start: installing the parts the program needs (one time only)..."
  "$PY" -m pip install --user -e . || { echo "Installation failed. Ask your IT support to run: pip install -e backend"; exit 1; }
fi
if [ ! -d ../engines/lib ]; then
  echo "Note: the simulation engines (EPA SWMM, EPANET) are not built yet, so water supply checks and"
  echo "network simulations will be skipped. To add them, run engines/build_engines.sh once."
fi
exec "$PY" -m cityinfra.app "$@"
