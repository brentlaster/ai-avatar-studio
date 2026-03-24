#!/bin/bash
###############################################################################
# Setup Coqui TTS (XTTS v2) in a dedicated conda environment
#
# Separate from the sadtalker env to avoid PyTorch version conflicts.
# SadTalker needs PyTorch 2.2.0; Coqui TTS needs PyTorch >= 2.4.
#
# Usage:  bash setup_tts.sh
###############################################################################
set -e

CONDA_ENV_NAME="tts"

echo "============================================================"
echo "  Setting up Coqui TTS (XTTS v2) — conda env '${CONDA_ENV_NAME}'"
echo "============================================================"

# --- Check for conda ---
if ! command -v conda &>/dev/null; then
    echo "ERROR: conda not found. Please install Miniconda or Anaconda first:"
    echo "  https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi

# --- Initialize conda for this shell session ---
eval "$(conda shell.bash hook)"

# --- Create conda environment if needed ---
if conda env list | grep -q "^${CONDA_ENV_NAME} "; then
    echo "Conda environment '${CONDA_ENV_NAME}' already exists."
    echo "To recreate:  conda env remove -n ${CONDA_ENV_NAME} && bash setup_tts.sh"
else
    echo "Creating conda environment '${CONDA_ENV_NAME}' with Python 3.10..."
    conda create -y -n "$CONDA_ENV_NAME" python=3.10
fi

# --- Find the conda env path and its Python/pip ---
CONDA_ENV_PATH="$(conda info --envs | grep "^${CONDA_ENV_NAME} " | awk '{print $NF}')"

if [ -z "$CONDA_ENV_PATH" ]; then
    CONDA_ENV_PATH="$(conda info --envs | grep "${CONDA_ENV_NAME}" | awk '{print $NF}')"
fi

if [ -z "$CONDA_ENV_PATH" ] || [ ! -d "$CONDA_ENV_PATH" ]; then
    echo "ERROR: Could not find conda environment path for '${CONDA_ENV_NAME}'"
    exit 1
fi

CONDA_PIP="$CONDA_ENV_PATH/bin/pip"
CONDA_PYTHON="$CONDA_ENV_PATH/bin/python"

echo ""
echo "Conda env path: $CONDA_ENV_PATH"
echo "Python: $($CONDA_PYTHON --version) at $CONDA_PYTHON"

# --- Install PyTorch (latest stable, includes MPS support on Apple Silicon) ---
echo ""
echo "Installing PyTorch (latest stable with MPS support)..."
"$CONDA_PIP" install --no-cache-dir torch torchvision torchaudio

# --- Install Coqui TTS ---
echo ""
echo "Installing Coqui TTS (XTTS v2)..."
"$CONDA_PIP" install --no-cache-dir TTS

# --- Pin transformers to avoid BeamSearchScorer removal (removed in >=4.45) ---
echo ""
echo "Pinning transformers to compatible version..."
"$CONDA_PIP" install --no-cache-dir "transformers>=4.33,<4.45"

# --- Quick sanity check ---
echo ""
echo "Verifying installation..."
"$CONDA_PYTHON" -c "
import torch
print(f'  PyTorch:       {torch.__version__}')
print(f'  MPS available: {torch.backends.mps.is_available()}')
try:
    from TTS.api import TTS
    print(f'  Coqui TTS:     OK')
except ImportError as e:
    print(f'  Coqui TTS:     FAILED ({e})')
"

echo ""
echo "============================================================"
echo "  Coqui TTS setup complete!"
echo ""
echo "  Conda env:   $CONDA_ENV_PATH"
echo "  Python:      $($CONDA_PYTHON --version)"
echo ""
echo "  The first TTS generation will download the XTTS v2 model"
echo "  (~2 GB). After that it's cached locally."
echo ""
echo "  Run the app from your base env (not this one):"
echo "    conda activate base"
echo "    python app.py"
echo "============================================================"
