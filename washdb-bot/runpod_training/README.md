# WashDB Model Fine-Tuning for RunPod

Fine-tune Mistral-7B for business verification and name standardization.

## Quick Start

### 1. Create RunPod Instance
- **Recommended GPU:** RTX 4090 ($0.44/hr) or A100 40GB ($1.49/hr)
- **Template:** PyTorch 2.1+ with CUDA
- **Disk:** 50 GB minimum

### 2. Upload Files
```bash
# On your local machine, create a tarball:
tar -czvf washdb-training.tar.gz runpod_training/ data/full_reasoning_training/

# Upload to RunPod via web terminal or SCP
```

### 3. Extract and Setup
```bash
# On RunPod
cd /workspace
tar -xzvf washdb-training.tar.gz

# Move data to expected location
mkdir -p runpod_training/data
mv data/full_reasoning_training/*.jsonl runpod_training/data/

cd runpod_training
pip install -r requirements.txt
```

### 4. Run Training
```bash
chmod +x run.sh
./run.sh
```

Or with custom settings:
```bash
python train.py \
    --train-data ./data/train.jsonl \
    --val-data ./data/val.jsonl \
    --epochs 3 \
    --batch-size 4
```

## GPU Recommendations

| GPU | VRAM | Batch Size | Est. Time | Cost |
|-----|------|------------|-----------|------|
| RTX 4090 | 24 GB | 4 | ~4-5 hrs | ~$2 |
| A100 40GB | 40 GB | 8 | ~2-3 hrs | ~$4 |
| H100 80GB | 80 GB | 16 | ~1-2 hrs | ~$6 |

## Training Data

- **Format:** ChatML (`<|im_start|>`, `<|im_end|>`)
- **Examples:** ~203,555 training, ~22,500 validation
- **Tasks:** Business verification (91%) + Name standardization (9%)

## Output

After training completes:
```
output/
├── final/           # Final merged model
│   ├── adapter_model.safetensors
│   ├── adapter_config.json
│   └── tokenizer files
├── checkpoint-*/    # Intermediate checkpoints
└── training_info.json
```

## Using the Model

### Load with PEFT (Recommended)
```python
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

base_model = "mistralai/Mistral-7B-Instruct-v0.2"
adapter_path = "./output/final"

tokenizer = AutoTokenizer.from_pretrained(adapter_path)
model = AutoModelForCausalLM.from_pretrained(base_model, device_map="auto")
model = PeftModel.from_pretrained(model, adapter_path)
```

### Merge LoRA into Base Model
```python
from peft import PeftModel
from transformers import AutoModelForCausalLM

model = AutoModelForCausalLM.from_pretrained(base_model)
model = PeftModel.from_pretrained(model, adapter_path)
merged_model = model.merge_and_unload()
merged_model.save_pretrained("./washdb-unified-merged")
```

## Troubleshooting

### OOM Error
Reduce batch size: `--batch-size 2`

### Slow Training
Increase batch size if VRAM allows: `--batch-size 8`

### CUDA Out of Memory on A100/H100
Try: `--batch-size 8 --grad-accum 2`
