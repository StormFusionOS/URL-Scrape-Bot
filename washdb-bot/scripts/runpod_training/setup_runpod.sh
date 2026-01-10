#!/bin/bash
# RunPod Setup Script for Unified WashDB LLM Training
# Run this after SSH into your RunPod instance

set -e

echo "=============================================="
echo "WashDB Unified LLM Training Setup"
echo "=============================================="

# Create directories
echo "Creating directories..."
mkdir -p /workspace/data
mkdir -p /workspace/output
mkdir -p /workspace/scripts

# Check for CUDA
echo ""
echo "Checking GPU..."
nvidia-smi --query-gpu=name,memory.total --format=csv

# Install Python requirements
echo ""
echo "Installing Python packages..."
pip install -q \
    transformers>=4.36.0 \
    datasets>=2.16.0 \
    accelerate>=0.25.0 \
    peft>=0.7.0 \
    bitsandbytes>=0.41.0 \
    trl>=0.7.0 \
    wandb \
    scipy \
    sentencepiece

# Clone llama.cpp for GGUF conversion (optional, can do later)
echo ""
echo "Cloning llama.cpp for GGUF conversion..."
if [ ! -d "/workspace/llama.cpp" ]; then
    cd /workspace
    git clone https://github.com/ggerganov/llama.cpp
    cd llama.cpp
    make -j$(nproc)
else
    echo "llama.cpp already exists"
fi

# Check if training data exists
echo ""
echo "Checking for training data..."
if [ -f "/workspace/data/unified_train_chatml.jsonl" ]; then
    echo "Training data found!"
    wc -l /workspace/data/unified_train_chatml.jsonl
    wc -l /workspace/data/unified_val_chatml.jsonl
else
    echo "WARNING: Training data not found!"
    echo "Please upload:"
    echo "  - unified_train_chatml.jsonl"
    echo "  - unified_val_chatml.jsonl"
    echo "to /workspace/data/"
fi

# Check if training script exists
echo ""
if [ -f "/workspace/train_unified_mistral.py" ]; then
    echo "Training script found!"
else
    echo "WARNING: Training script not found!"
    echo "Please upload train_unified_mistral.py to /workspace/"
fi

echo ""
echo "=============================================="
echo "Setup Complete!"
echo "=============================================="
echo ""
echo "Next steps:"
echo "1. Upload training data to /workspace/data/"
echo "2. Upload train_unified_mistral.py to /workspace/"
echo "3. Run: python /workspace/train_unified_mistral.py"
echo ""
echo "To run in background:"
echo "  nohup python train_unified_mistral.py > training.log 2>&1 &"
echo "  tail -f training.log"
echo ""
