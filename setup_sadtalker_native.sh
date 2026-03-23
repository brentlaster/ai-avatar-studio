#!/bin/bash
###############################################################################
# Setup SadTalker natively on macOS Apple Silicon using Conda
#
# Uses Python 3.10 + PyTorch 2.2.0 (native ARM, has MPS GPU support)
# with numpy <2.0 to avoid breaking changes SadTalker can't handle.
#
# Usage:  bash setup_sadtalker_native.sh
#
# IMPORTANT: If you have a Python venv active, deactivate it first:
#   deactivate
###############################################################################
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SADTALKER_DIR="$SCRIPT_DIR/SadTalker"
CONDA_ENV_NAME="sadtalker"

echo "============================================================"
echo "  Setting up SadTalker natively (conda + Python 3.10)"
echo "============================================================"

# --- Check for conda ---
if ! command -v conda &>/dev/null; then
    echo "ERROR: conda not found. Please install Miniconda or Anaconda first:"
    echo "  https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi

# --- Initialize conda for this shell session ---
eval "$(conda shell.bash hook)"

# --- Deactivate any active venv to prevent PATH conflicts ---
if [ -n "$VIRTUAL_ENV" ]; then
    echo "Deactivating active Python venv ($VIRTUAL_ENV)..."
    deactivate 2>/dev/null || true
fi

# --- Create conda environment if needed ---
if conda env list | grep -q "^${CONDA_ENV_NAME} "; then
    echo "Conda environment '${CONDA_ENV_NAME}' already exists."
    echo "To recreate:  conda env remove -n ${CONDA_ENV_NAME} && bash setup_sadtalker_native.sh"
else
    echo "Creating conda environment '${CONDA_ENV_NAME}' with Python 3.10..."
    conda create -y -n "$CONDA_ENV_NAME" python=3.10
fi

# --- Find the conda env path and its Python/pip directly ---
CONDA_ENV_PATH="$(conda info --envs | grep "^${CONDA_ENV_NAME} " | awk '{print $NF}')"

if [ -z "$CONDA_ENV_PATH" ]; then
    # Try alternate pattern (active env marked with *)
    CONDA_ENV_PATH="$(conda info --envs | grep "${CONDA_ENV_NAME}" | awk '{print $NF}')"
fi

if [ -z "$CONDA_ENV_PATH" ] || [ ! -d "$CONDA_ENV_PATH" ]; then
    echo "ERROR: Could not find conda environment path for '${CONDA_ENV_NAME}'"
    echo "Try running:  conda env list"
    exit 1
fi

CONDA_PIP="$CONDA_ENV_PATH/bin/pip"
CONDA_PYTHON="$CONDA_ENV_PATH/bin/python"

echo ""
echo "Conda env path: $CONDA_ENV_PATH"
echo "Python: $($CONDA_PYTHON --version) at $CONDA_PYTHON"
echo "Pip:    $CONDA_PIP"

# --- Verify we're using the right Python ---
PY_VERSION=$($CONDA_PYTHON --version 2>&1)
if [[ "$PY_VERSION" != *"3.10"* ]]; then
    echo "ERROR: Expected Python 3.10 but got: $PY_VERSION"
    echo "Try:  conda env remove -n ${CONDA_ENV_NAME} && bash setup_sadtalker_native.sh"
    exit 1
fi

# --- Install PyTorch 2.2.0 (native ARM, includes MPS support) ---
echo ""
echo "Installing PyTorch 2.2.0 (native ARM build with MPS support)..."
"$CONDA_PIP" install --no-cache-dir \
    torch==2.2.0 \
    torchvision==0.17.0 \
    torchaudio==2.2.0

# --- Install SadTalker dependencies ---
echo ""
echo "Installing SadTalker dependencies..."
"$CONDA_PIP" install --no-cache-dir \
    "numpy>=1.23,<2.0" \
    "scipy>=1.9,<1.12" \
    opencv-python-headless \
    scikit-image \
    "Pillow>=9.0,<11.0" \
    imageio \
    imageio-ffmpeg \
    "librosa>=0.9,<0.11" \
    pydub \
    safetensors \
    tqdm \
    yacs \
    pyyaml \
    joblib \
    dlib \
    face_alignment \
    "kornia>=0.6,<0.8" \
    "gfpgan>=1.3,<1.4" \
    "basicsr>=1.4,<1.5" \
    "facexlib>=0.3,<0.4" \
    "realesrgan>=0.3,<0.4"

# --- Clone SadTalker if not already present ---
if [ ! -d "$SADTALKER_DIR" ]; then
    echo ""
    echo "Cloning SadTalker..."
    git clone --depth 1 https://github.com/OpenTalker/SadTalker.git "$SADTALKER_DIR"
else
    echo ""
    echo "SadTalker already cloned at $SADTALKER_DIR"
fi

# --- Download model checkpoints ---
if [ ! -f "$SADTALKER_DIR/checkpoints/epoch_20.pth" ]; then
    echo ""
    echo "Downloading SadTalker model checkpoints..."
    cd "$SADTALKER_DIR"
    bash scripts/download_models.sh
    cd "$SCRIPT_DIR"
else
    echo ""
    echo "Model checkpoints already downloaded."
fi

# --- Quick sanity check ---
echo ""
echo "Verifying installation..."
"$CONDA_PYTHON" -c "
import torch
import numpy as np
print(f'  PyTorch:       {torch.__version__}')
print(f'  NumPy:         {np.__version__}')
print(f'  MPS available: {torch.backends.mps.is_available()}')
print(f'  Device:        {\"mps\" if torch.backends.mps.is_available() else \"cpu\"}')
"

echo ""
echo "============================================================"
echo "  SadTalker native setup complete!"
echo ""
echo "  Conda env:   $CONDA_ENV_PATH"
echo "  Python:      $($CONDA_PYTHON --version)"
echo "  SadTalker:   $SADTALKER_DIR"
echo ""
echo "  Now run the app:  python app.py"
echo "  Select 'SadTalker' as the video backend."
echo "============================================================"
