#!/bin/bash
# ============================================================
#  AI Avatar Studio v2 — Setup (API-based version)
#  Much simpler than v1 — just needs ffmpeg and a few pip packages.
# ============================================================

set -e

echo "============================================"
echo "  AI Avatar Studio v2 — Setup"
echo "============================================"
echo ""

# Check ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "Installing ffmpeg via Homebrew ..."
    if command -v brew &> /dev/null; then
        brew install ffmpeg
    else
        echo "ERROR: ffmpeg is required. Install from https://ffmpeg.org or via Homebrew."
        exit 1
    fi
fi
echo "  ffmpeg ✓"

# Create venv
echo "Creating virtual environment ..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel

# Install dependencies (just 3 packages!)
echo "Installing dependencies ..."
pip install gradio requests ffmpeg-python

echo ""
echo "============================================"
echo "  Setup complete!"
echo ""
echo "  Before running, add your API keys:"
echo "    1. Edit config.py with your keys, OR"
echo "    2. Set environment variables:"
echo "       export ELEVENLABS_API_KEY=your-key"
echo "       export DID_API_KEY=your-key"
echo ""
echo "  Then start the app:"
echo "    source venv/bin/activate"
echo "    python app.py"
echo ""
echo "  Sign up for API keys:"
echo "    ElevenLabs: https://elevenlabs.io"
echo "    D-ID:       https://studio.d-id.com"
echo "============================================"
