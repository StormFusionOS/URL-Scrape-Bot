# Unified WashDB LLM Training on RunPod

This guide walks you through training a unified Mistral-7B model that can perform both **business verification** and **name standardization** tasks.

## Training Data Summary

| Dataset | Examples | Description |
|---------|----------|-------------|
| Verification | 10,213 | Balanced pass/fail business verification examples |
| Standardization | 16,795 | Claude-annotated name extraction examples |
| Hard Negatives | 1,400 | Franchises, edge cases, similar names |
| **Training** | **27,008** | Enhanced training set |
| **Validation** | **2,884** | Held-out validation set |
| **Total** | **29,892** | Complete dataset |

### Enhancements Added
- Hard negative mining (franchises, similar names with different verdicts)
- Edge cases (low confidence, conflicting signals)
- Non-service businesses (negative examples)
- Deduplicated (removed 340 duplicates)

## Step 1: Prepare RunPod Instance

### Recommended GPU
- **A100 40GB** - Best performance, ~2-3 hours training
- **A6000 48GB** - Good alternative, ~3-4 hours
- **RTX 4090 24GB** - Works with reduced batch size

### Template
Use the **RunPod PyTorch 2.1** template or similar with CUDA 12.x

### Storage
- Minimum 50GB workspace volume
- Training outputs ~15GB

## Step 2: Upload Training Data

### Option A: SCP from local machine
```bash
# On your local machine
cd /home/rivercityscrape/URL-Scrape-Bot/washdb-bot/data/unified_training

# Upload to RunPod (replace with your RunPod SSH details)
scp -P <PORT> unified_train_chatml.jsonl unified_val_chatml.jsonl root@<RUNPOD_IP>:/workspace/data/
```

### Option B: Use runpodctl
```bash
runpodctl send /home/rivercityscrape/URL-Scrape-Bot/washdb-bot/data/unified_training/unified_train_chatml.jsonl
runpodctl send /home/rivercityscrape/URL-Scrape-Bot/washdb-bot/data/unified_training/unified_val_chatml.jsonl
```

### Option C: Upload via Jupyter
1. Open Jupyter Lab on your RunPod instance
2. Navigate to `/workspace/data/`
3. Upload the JSONL files

## Step 3: Upload Training Script

```bash
scp -P <PORT> train_unified_mistral.py root@<RUNPOD_IP>:/workspace/
```

## Step 4: Run Training

SSH into your RunPod instance:
```bash
ssh -p <PORT> root@<RUNPOD_IP>
```

Install dependencies and start training:
```bash
cd /workspace

# Create data directory
mkdir -p /workspace/data
mkdir -p /workspace/output

# Move data if needed
mv unified_*.jsonl /workspace/data/

# Install requirements (auto-installed by script, but can pre-install)
pip install transformers datasets accelerate peft bitsandbytes trl wandb scipy

# Start training (with or without wandb)
python train_unified_mistral.py

# Or run in background with logs
nohup python train_unified_mistral.py > training.log 2>&1 &
tail -f training.log
```

### Monitor Training
- **Wandb**: If configured, view at https://wandb.ai
- **Logs**: `tail -f training.log`
- **GPU**: `watch nvidia-smi`

## Step 5: Export to GGUF (for Ollama)

After training completes, merge LoRA weights and convert to GGUF:

```bash
# Merge LoRA weights
python train_unified_mistral.py --export

# Install llama.cpp for GGUF conversion
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
make -j

# Convert to GGUF
pip install sentencepiece
python convert-hf-to-gguf.py /workspace/output/unified-washdb-mistral/merged \
    --outtype f16 \
    --outfile /workspace/output/unified-washdb-f16.gguf

# Quantize to Q4_K_M (recommended for production)
./llama-quantize /workspace/output/unified-washdb-f16.gguf \
    /workspace/output/unified-washdb-q4km.gguf Q4_K_M
```

## Step 6: Download Model

```bash
# On RunPod, compress the model
cd /workspace/output
zip -r unified-washdb-model.zip unified-washdb-q4km.gguf Modelfile.unified

# Download to local machine
scp -P <PORT> root@<RUNPOD_IP>:/workspace/output/unified-washdb-q4km.gguf ./
scp -P <PORT> root@<RUNPOD_IP>:/workspace/output/unified-washdb-mistral/merged/* ./merged/
```

## Step 7: Create Ollama Model (Local)

On your local machine with Ollama:

```bash
# Copy the GGUF file
cp unified-washdb-q4km.gguf /path/to/models/

# Create Modelfile
cat > Modelfile <<'EOF'
FROM ./unified-washdb-q4km.gguf

TEMPLATE "<s>[INST] {{ .System }}

{{ .Prompt }} [/INST]"

SYSTEM """You are a business intelligence assistant for WashDB that performs two tasks:

TASK 1 - VERIFICATION: Determine if a company is a legitimate exterior cleaning service provider.
Target services: Pressure washing, Window cleaning, Soft washing, Roof cleaning, Gutter cleaning, Solar panel cleaning, Fleet washing, Wood restoration.

TASK 2 - STANDARDIZATION: Extract and standardize the official business name from website information.

For verification requests, respond with JSON:
{"legitimate": true/false, "confidence": 0.0-1.0, "services": {...}, "reasoning": "..."}

For standardization requests, respond with just the standardized business name."""

PARAMETER temperature 0.1
PARAMETER top_p 0.9
PARAMETER num_ctx 2048
PARAMETER stop </s>
PARAMETER stop [INST]
PARAMETER stop [/INST]
EOF

# Create Ollama model
ollama create unified-washdb -f Modelfile

# Test it
ollama run unified-washdb "Is this a legitimate service provider? Company: ABC Pressure Washing, Website: abcpressurewashing.com, Services: pressure washing, soft washing"
```

## Testing the Model

### Verification Task
```bash
ollama run unified-washdb "Company: Clean Pro Services
Website: https://cleanproservices.com
Phone: (555) 123-4567
Services: Pressure washing, window cleaning, gutter cleaning
Address: 123 Main St, Anytown, USA

Is this a legitimate service provider?"
```

### Standardization Task
```bash
ollama run unified-washdb "Extract business name:
Title: Professional Pressure Washing Services - Clean Pro LLC
Domain: cleanprollc.com
Homepage: Welcome to Clean Pro LLC, your trusted partner for all pressure washing needs..."
```

## Training Configuration

| Parameter | Value | Notes |
|-----------|-------|-------|
| Base Model | Mistral-7B-Instruct-v0.2 | Best for instruction following |
| LoRA Rank | 64 | Higher = more capacity |
| LoRA Alpha | 128 | 2x rank is standard |
| Learning Rate | 2e-4 | Good for LoRA |
| Batch Size | 16 (4 x 4 accum) | Effective batch size |
| Epochs | 3 | Usually sufficient |
| Max Seq Length | 2048 | Covers most examples |
| Quantization | 4-bit NF4 | Saves VRAM |

## Troubleshooting

### Out of Memory
- Reduce `batch_size` to 2
- Reduce `max_seq_length` to 1024
- Enable `gradient_checkpointing` (already enabled)

### Slow Training
- Ensure GPU is being used: `nvidia-smi`
- Check for CPU bottleneck in data loading
- Use `packing=True` in SFTTrainer for faster training

### Model Not Learning
- Check training loss is decreasing
- Verify data format is correct
- Try lower learning rate (1e-4)

## Files Reference

| File | Description |
|------|-------------|
| `train_unified_mistral.py` | Main training script |
| `Modelfile.unified` | Ollama model configuration |
| `unified_train_chatml.jsonl` | Training data (ChatML format) |
| `unified_val_chatml.jsonl` | Validation data (ChatML format) |
| `training_stats.json` | Dataset statistics |

## Cost Estimate

| GPU | Time | Cost (RunPod) |
|-----|------|---------------|
| A100 40GB | ~2-3 hours | ~$5-8 |
| A6000 48GB | ~3-4 hours | ~$4-6 |
| RTX 4090 24GB | ~4-5 hours | ~$3-5 |
