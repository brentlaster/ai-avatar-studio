#!/bin/bash
# ============================================================
#  AI Avatar Studio v2 — Full Setup
#
#  One script to install everything:
#    1. System tools (ffmpeg, LibreOffice, poppler)
#    2. Python app dependencies (gradio, etc.)
#    3. SadTalker conda env (free video generation)
#    4. Coqui TTS conda env (free voice cloning)
#
#  Usage:  bash setup.sh
#
#  Each step is idempotent — safe to re-run if interrupted.
#  Individual components can still be set up separately:
#    bash setup_sadtalker_native.sh
#    bash setup_tts.sh
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================================"
echo "  AI Avatar Studio v2 — Full Setup"
echo "============================================================"
echo ""

# ==============================================================
# Step 1: System tools (ffmpeg, LibreOffice, poppler)
# ==============================================================
echo "[1/4] Checking system tools ..."

if ! command -v ffmpeg &> /dev/null; then
    echo "  Installing ffmpeg via Homebrew ..."
    if command -v brew &> /dev/null; then
        brew install ffmpeg
    else
        echo "  WARNING: ffmpeg not found and Homebrew not available."
        echo "           Install ffmpeg manually: https://ffmpeg.org"
    fi
fi
command -v ffmpeg &>/dev/null && echo "  ffmpeg ✓" || echo "  ffmpeg ✗ (required — install manually)"

# LibreOffice + poppler for high-quality slide rendering
if command -v brew &> /dev/null; then
    if [ ! -d "/Applications/LibreOffice.app" ] && [ ! -d "$HOME/Applications/LibreOffice.app" ]; then
        echo "  Installing LibreOffice (for Presentation Mode slide rendering) ..."
        brew install --cask libreoffice
    fi
    echo "  LibreOffice ✓"

    if ! command -v pdftoppm &> /dev/null; then
        echo "  Installing poppler (for PDF-to-image conversion) ..."
        brew install poppler
    fi
    command -v pdftoppm &>/dev/null && echo "  poppler ✓" || echo "  poppler ✗ (optional — slides will use fallback renderer)"
else
    echo "  Homebrew not found — skipping LibreOffice & poppler."
    echo "  Install Homebrew first if you want high-quality slide rendering:"
    echo "    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
fi

# ==============================================================
# Step 2: Python app dependencies
# ==============================================================
echo ""
echo "[2/4] Installing Python app dependencies ..."

pip install --quiet gradio requests ffmpeg-python python-pptx Pillow 2>/dev/null \
    || pip install gradio requests ffmpeg-python python-pptx Pillow
echo "  App dependencies ✓"

# ==============================================================
# Step 3: SadTalker (free video generation)
# ==============================================================
echo ""
echo "[3/4] Setting up SadTalker (free video generation) ..."

if [ -f "$SCRIPT_DIR/setup_sadtalker_native.sh" ]; then
    bash "$SCRIPT_DIR/setup_sadtalker_native.sh"
else
    echo "  WARNING: setup_sadtalker_native.sh not found — skipping SadTalker setup"
fi

# ==============================================================
# Step 4: Coqui TTS (free voice cloning)
# ==============================================================
echo ""
echo "[4/4] Setting up Coqui TTS (free voice cloning) ..."

if [ -f "$SCRIPT_DIR/setup_tts.sh" ]; then
    bash "$SCRIPT_DIR/setup_tts.sh"
else
    echo "  WARNING: setup_tts.sh not found — skipping Coqui TTS setup"
fi

# ==============================================================
# Done!
# ==============================================================
echo ""
echo "============================================================"
echo "  Setup complete! Here's what was installed:"
echo ""
echo "  System tools:"
command -v ffmpeg &>/dev/null && echo "    ✓ ffmpeg" || echo "    ✗ ffmpeg (install manually)"
[ -d "/Applications/LibreOffice.app" ] || [ -d "$HOME/Applications/LibreOffice.app" ] \
    && echo "    ✓ LibreOffice" || echo "    ✗ LibreOffice (optional)"
command -v pdftoppm &>/dev/null && echo "    ✓ poppler" || echo "    ✗ poppler (optional)"
echo ""
echo "  Conda environments:"
conda info --envs 2>/dev/null | grep -q "^sadtalker " && echo "    ✓ sadtalker (video)" || echo "    ✗ sadtalker"
conda info --envs 2>/dev/null | grep -q "^tts " && echo "    ✓ tts (voice cloning)" || echo "    ✗ tts"
echo ""
echo "  To start the app:"
echo "    bash start.sh"
echo ""
echo "  API keys (optional — only for ElevenLabs/D-ID):"
echo "    Set them in the Settings tab of the app UI."
echo "============================================================"
