#!/usr/bin/env bash
# StudyFlow launcher & toggle script (Linux & macOS)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect Python interpreter (prefer valid virtualenv, fallback to system python)
if [ -f "$SCRIPT_DIR/.venv/bin/python" ] && "$SCRIPT_DIR/.venv/bin/python" -c "import PyQt5" 2>/dev/null; then
    PYTHON_CMD="$SCRIPT_DIR/.venv/bin/python"
elif [ -f "$SCRIPT_DIR/venv/bin/python" ] && "$SCRIPT_DIR/venv/bin/python" -c "import PyQt5" 2>/dev/null; then
    PYTHON_CMD="$SCRIPT_DIR/venv/bin/python"
elif [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON_CMD="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "Error: Python 3 not found. Run ./setup.sh to set up the environment." >&2
    exit 1
fi

# Set X11 display environment if applicable (Linux)
export DISPLAY="${DISPLAY:-:0.0}"
if [ -n "$HOME" ] && [ -f "$HOME/.Xauthority" ]; then
    export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"
fi

exec "$PYTHON_CMD" "$SCRIPT_DIR/study_timer.py" "$@"
