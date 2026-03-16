#!/usr/bin/env bash
# ============================================================================
# Privacy Shield SLM - Colab Environment Setup
#
# IMPORTANT: Before running this script, mount Google Drive in your notebook:
#
#   from google.colab import drive
#   drive.mount('/content/drive')
#
# Then run:
#   !bash scripts/colab_setup.sh
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================="
echo "  Privacy Shield SLM - Colab Setup"
echo "========================================="

# -------------------------------------------
# 1. Install Python dependencies
# -------------------------------------------
echo ""
echo "[1/4] Installing Python dependencies..."
pip install -q -r "$PROJECT_DIR/requirements.txt"
echo "  Done."

# -------------------------------------------
# 2. Install NER-specific dependencies
# -------------------------------------------
echo ""
echo "[2/3] Installing NER dependencies (seqeval, evaluate)..."
pip install -q seqeval>=1.2.2 evaluate>=0.4
echo "  Done."

# -------------------------------------------
# 3. Symlink output and data to Google Drive
# -------------------------------------------
echo ""
echo "[3/3] Creating Google Drive symlinks..."

DRIVE_OUTPUT="/content/drive/MyDrive/privacy-shield-output"
DRIVE_DATA="/content/drive/MyDrive/privacy-shield-data"

if [ ! -d "/content/drive/MyDrive" ]; then
    echo "  WARNING: Google Drive not mounted at /content/drive/MyDrive"
    echo "  Please mount it first with: drive.mount('/content/drive')"
    exit 1
fi

mkdir -p "$DRIVE_OUTPUT"
mkdir -p "$DRIVE_DATA"

ln -sf "$DRIVE_OUTPUT" "$PROJECT_DIR/output"
echo "  output/ -> $DRIVE_OUTPUT"

ln -sf "$DRIVE_DATA" "$PROJECT_DIR/data"
echo "  data/   -> $DRIVE_DATA"

echo ""
echo "========================================="
echo "  Setup complete!"
echo "========================================="
