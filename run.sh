#!/bin/bash
set -e

echo "================================================"
echo "  TTS Voice Clone Tool - Setup & Launch"
echo "================================================"
echo ""

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"

# Check Python
PYTHON=""
for cmd in python3 python; do
    if command -v $cmd &>/dev/null; then
        PYTHON=$cmd
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "Error: Python 3 is not installed."
    exit 1
fi

PY_VERSION=$($PYTHON --version 2>&1 | awk '{print $2}' | awk -F. '{print $1"."$2}')
echo "Python version: $($PYTHON --version)"

# Create virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# Install dependencies
echo "Installing dependencies..."
pip install -q --upgrade pip
pip install -r "$PROJECT_DIR/requirements.txt"

# Fix bangla package compatibility with Python 3.9
BANGLA_FILE="$VENV_DIR/lib/python$PY_VERSION/site-packages/bangla/__init__.py"
if [ -f "$BANGLA_FILE" ]; then
    if grep -q "bool | None" "$BANGLA_FILE" 2>/dev/null; then
        echo "Patching bangla package for Python 3.9 compatibility..."
        sed -i '' 's/ordinal: bool | None/ordinal: typing.Optional[bool]/' "$BANGLA_FILE"
        HEADER=$(head -1 "$BANGLA_FILE")
        if echo "$HEADER" | grep -v -q "import typing"; then
            sed -i '' '1s/^/import typing\n/' "$BANGLA_FILE"
        fi
    fi
fi

# Create necessary directories
mkdir -p "$PROJECT_DIR/uploads" "$PROJECT_DIR/output" "$PROJECT_DIR/voice_profiles" "$PROJECT_DIR/templates"

echo ""
echo "================================================"
echo "  Setup complete!"
echo "================================================"
echo ""
echo "Starting the server..."
echo "Open http://localhost:8080 in your browser"
echo ""

cd "$PROJECT_DIR"
$PYTHON app.py --host 0.0.0.0 --port 8080