#!/bin/bash
# ============================================================
#  AI Avatar Studio v2 — Start the app
#
#  Usage:  bash start.sh
#
#  This script handles conda environment activation automatically
#  so you don't need to think about which env to be in.
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Initialize conda for this shell session ---
if command -v conda &>/dev/null; then
    eval "$(conda shell.bash hook)"
    conda activate base 2>/dev/null || true
fi

# --- Check that core dependencies are available ---
if ! python -c "import gradio" 2>/dev/null; then
    echo "ERROR: gradio not found. Run setup first:"
    echo "  bash setup.sh"
    exit 1
fi

echo "============================================================"
echo "  Starting AI Avatar Studio v2 ..."
echo "============================================================"
echo ""

cd "$SCRIPT_DIR"
python app.py
