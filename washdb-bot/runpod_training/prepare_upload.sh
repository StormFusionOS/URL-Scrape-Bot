#!/bin/bash
# Prepare training package for RunPod upload
# Creates a single tarball with everything needed

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_FILE="$PROJECT_DIR/washdb-runpod-training.tar.gz"

echo "=============================================="
echo "Preparing RunPod Training Package"
echo "=============================================="

# Check training data exists (using cleaned data)
TRAIN_DATA="$PROJECT_DIR/data/cleaned_training"
if [ ! -d "$TRAIN_DATA" ]; then
    echo "ERROR: Training data not found at $TRAIN_DATA"
    echo "Run export_with_reasoning.py first"
    exit 1
fi

echo "Training data: $TRAIN_DATA"
echo ""

# Create temp directory for packaging
TEMP_DIR=$(mktemp -d)
mkdir -p "$TEMP_DIR/washdb_training/data"

# Copy training scripts
echo "Copying training scripts..."
cp "$SCRIPT_DIR/train.py" "$TEMP_DIR/washdb_training/"
cp "$SCRIPT_DIR/requirements.txt" "$TEMP_DIR/washdb_training/"
cp "$SCRIPT_DIR/run.sh" "$TEMP_DIR/washdb_training/"
cp "$SCRIPT_DIR/README.md" "$TEMP_DIR/washdb_training/"

# Copy training data
echo "Copying training data..."
cp "$TRAIN_DATA/train.jsonl" "$TEMP_DIR/washdb_training/data/"
cp "$TRAIN_DATA/val.jsonl" "$TEMP_DIR/washdb_training/data/"
cp "$TRAIN_DATA/stats.json" "$TEMP_DIR/washdb_training/data/"

# Show sizes
echo ""
echo "Package contents:"
du -sh "$TEMP_DIR/washdb_training/"*
du -sh "$TEMP_DIR/washdb_training/data/"*

# Create tarball
echo ""
echo "Creating tarball..."
cd "$TEMP_DIR"
tar -czvf "$OUTPUT_FILE" washdb_training/

# Cleanup
rm -rf "$TEMP_DIR"

# Show result
echo ""
echo "=============================================="
echo "Package created successfully!"
echo "=============================================="
echo "File: $OUTPUT_FILE"
echo "Size: $(du -h "$OUTPUT_FILE" | cut -f1)"
echo ""
echo "Upload to RunPod:"
echo "  1. Open RunPod terminal"
echo "  2. Upload via web or: scp $OUTPUT_FILE root@<pod-ip>:/workspace/"
echo "  3. Extract: cd /workspace && tar -xzvf washdb-runpod-training.tar.gz"
echo "  4. Run: cd washdb_training && ./run.sh"
