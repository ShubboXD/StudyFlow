#!/usr/bin/env bash
# StudyFlow automated setup script for Linux & macOS

echo "=========================================="
echo "         StudyFlow Quick Setup            "
echo "=========================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Verify Python 3
if ! command -v python3 &>/dev/null; then
    echo "[-] Python 3 was not found on your system."
    echo "    Please install it:"
    echo "    - Debian/Ubuntu: sudo apt update && sudo apt install -y python3 python3-pip python3-venv"
    echo "    - Fedora:        sudo dnf install -y python3 python3-pip"
    echo "    - Arch Linux:    sudo pacman -S python python-pip"
    echo "    - macOS:         brew install python"
    exit 1
fi

PYTHON_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "[+] Detected Python $PYTHON_VER"

# 2. Virtual environment creation
VENV_OK=false
if [ -f ".venv/bin/pip" ] && [ -f ".venv/bin/python" ]; then
    echo "[+] Existing valid virtual environment found in .venv"
    VENV_OK=true
else
    # Remove any broken/incomplete venv
    rm -rf .venv 2>/dev/null || true
    echo "[+] Creating virtual environment in .venv..."
    if python3 -m venv --system-site-packages .venv 2>/dev/null && [ -f ".venv/bin/pip" ]; then
        VENV_OK=true
        echo "[+] Virtual environment created."
    elif python3 -m venv .venv 2>/dev/null && [ -f ".venv/bin/pip" ]; then
        VENV_OK=true
        echo "[+] Virtual environment created."
    else
        rm -rf .venv 2>/dev/null || true
        echo "[!] Notice: Standard venv creation unavailable without python3-venv."
    fi
fi

# 3. Install dependencies
if [ "$VENV_OK" = true ]; then
    echo "[+] Installing dependencies into .venv..."
    .venv/bin/pip install --upgrade pip --quiet 2>/dev/null || true
    .venv/bin/pip install -r requirements.txt
else
    echo "[+] Checking existing PyQt5 installation..."
    if python3 -c "import PyQt5" 2>/dev/null; then
        echo "[+] PyQt5 is already available in the Python environment!"
    else
        echo "[+] Installing dependencies for current user via pip..."
        python3 -m pip install --user -r requirements.txt --break-system-packages 2>/dev/null || \
        python3 -m pip install --user -r requirements.txt
    fi
fi

# 4. Make scripts executable
chmod +x run.sh setup.sh main.py study_timer.py

echo ""
echo "=========================================="
echo "[✓] Setup completed successfully!"
echo "=========================================="
echo ""
echo "To start StudyFlow now, run:"
echo "  ./run.sh"
echo ""
echo "Or toggle visibility at any time with:"
echo "  ./run.sh --toggle"
echo ""
