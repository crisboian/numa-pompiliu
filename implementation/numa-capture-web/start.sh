#!/bin/bash
# NUMA Capture Web — start script
VENV_PYTHON=/usr/local/lib/hermes-agent/venv/bin/python3
cd "$(dirname "$0")/backend"
exec $VENV_PYTHON server.py "$@"
