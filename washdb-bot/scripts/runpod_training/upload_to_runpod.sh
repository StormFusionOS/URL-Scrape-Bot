#!/bin/bash
# Upload training files to RunPod
# Usage: ./upload_to_runpod.sh <RUNPOD_IP> <RUNPOD_PORT>
#
# Example: ./upload_to_runpod.sh 195.26.233.39 38895

set -e

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: $0 <RUNPOD_IP> <RUNPOD_PORT>"
    echo "Example: $0 195.26.233.39 38895"
    exit 1
fi

RUNPOD_IP=$1
RUNPOD_PORT=$2
RUNPOD_HOST="root@${RUNPOD_IP}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Use combined dataset (enriched + enhanced)
DATA_DIR="/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/data/combined_training"

echo "=============================================="
echo "Uploading WashDB Training Files to RunPod"
echo "=============================================="
echo "Target: ${RUNPOD_HOST}:${RUNPOD_PORT}"
echo ""

# Test connection
echo "Testing SSH connection..."
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -p ${RUNPOD_PORT} ${RUNPOD_HOST} "echo 'Connection successful!'" || {
    echo "Failed to connect to RunPod. Check IP and port."
    exit 1
}

# Create directories on RunPod
echo ""
echo "Creating directories on RunPod..."
ssh -p ${RUNPOD_PORT} ${RUNPOD_HOST} "mkdir -p /workspace/data /workspace/scripts"

# Upload training data
echo ""
echo "Uploading training data (130 MB combined dataset)..."
scp -P ${RUNPOD_PORT} \
    ${DATA_DIR}/combined_train.jsonl \
    ${DATA_DIR}/combined_val.jsonl \
    ${DATA_DIR}/combined_stats.json \
    ${RUNPOD_HOST}:/workspace/data/

# Upload training scripts
echo ""
echo "Uploading training scripts..."
scp -P ${RUNPOD_PORT} \
    ${SCRIPT_DIR}/train_unified_mistral.py \
    ${SCRIPT_DIR}/setup_runpod.sh \
    ${SCRIPT_DIR}/Modelfile.unified \
    ${RUNPOD_HOST}:/workspace/

# Verify uploads
echo ""
echo "Verifying uploads..."
ssh -p ${RUNPOD_PORT} ${RUNPOD_HOST} "ls -la /workspace/data/*.jsonl && ls -la /workspace/*.py"

echo ""
echo "=============================================="
echo "Upload Complete!"
echo "=============================================="
echo ""
echo "SSH into RunPod and start training:"
echo "  ssh -p ${RUNPOD_PORT} ${RUNPOD_HOST}"
echo ""
echo "Then run:"
echo "  bash /workspace/setup_runpod.sh"
echo "  python /workspace/train_unified_mistral.py"
echo ""
