#!/usr/bin/env bash
# Convenience launcher for the Signal-Server GUI (testing use).
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
export PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$HERE/.venv/bin/python" -m signal_gui "$@"
