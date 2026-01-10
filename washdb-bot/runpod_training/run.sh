#!/bin/bash
# WashDB Fine-Tuning Script for RunPod
# Usage: ./run.sh

set -e

echo "=============================================="
echo "WashDB Model Fine-Tuning"
echo "=============================================="

# Check CUDA
echo "Checking GPU..."
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

# Install requirements if not done
if ! python -c "import peft" 2>/dev/null; then
    echo "Installing requirements..."
    pip install -r requirements.txt
fi

# Default paths
TRAIN_DATA="${TRAIN_DATA:-./data/train.jsonl}"
VAL_DATA="${VAL_DATA:-./data/val.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-./output}"

# Check data exists
if [ ! -f "$TRAIN_DATA" ]; then
    echo "ERROR: Training data not found at $TRAIN_DATA"
    echo "Please upload train.jsonl to ./data/"
    exit 1
fi

# Run training
echo ""
echo "Starting training..."
echo "Train data: $TRAIN_DATA"
echo "Val data: $VAL_DATA"
echo "Output: $OUTPUT_DIR"
echo ""

python train.py \
    --train-data "$TRAIN_DATA" \
    --val-data "$VAL_DATA" \
    --output-dir "$OUTPUT_DIR" \
    --epochs 3 \
    --batch-size 2 \
    --grad-accum 8

echo ""
echo "=============================================="
echo "Training complete!"
echo "Model saved to: $OUTPUT_DIR/final"
echo "=============================================="
