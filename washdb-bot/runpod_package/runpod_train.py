#!/usr/bin/env python3
"""
RunPod Training Script for Mistral 7B Verification Model

This is a self-contained script for training on RunPod with an A100 GPU.

Usage on RunPod:
    1. Upload this script and balanced_all_20251209_101213.jsonl
    2. pip install unsloth transformers datasets trl peft accelerate bitsandbytes
    3. python runpod_train.py

The script will:
    - Load the training data
    - Fine-tune Mistral 7B with LoRA
    - Save the model in both LoRA and GGUF format
    - Create an Ollama Modelfile
"""

import json
import sys
from pathlib import Path
from datetime import datetime

# Training configuration - OPTIMIZED based on failed runs
CONFIG = {
    "model_name": "unsloth/mistral-7b-v0.3-bnb-4bit",
    "max_seq_length": 2048,
    "epochs": 3,
    "batch_size": 4,  # Larger batch on A100
    "gradient_accumulation": 4,
    "learning_rate": 5e-5,  # Lower LR to prevent mode collapse
    "warmup_ratio": 0.05,  # 5% warmup
    "lora_r": 16,
    "lora_alpha": 16,
    "output_dir": "./verification-mistral-output",
}


def load_training_data(filepath: str) -> list:
    """Load training data from JSONL file using Mistral Instruct format."""
    data = []
    with open(filepath, 'r') as f:
        for line in f:
            record = json.loads(line.strip())
            messages = record.get('messages', [])

            system_content = ""
            user_content = ""
            assistant_content = ""

            for msg in messages:
                role = msg['role']
                content = msg['content']
                if role == 'system':
                    system_content = content
                elif role == 'user':
                    user_content = content
                elif role == 'assistant':
                    assistant_content = content

            # Format using Mistral Instruct template
            if system_content:
                text = f"<s>[INST] {system_content}\n\n{user_content} [/INST] {assistant_content}</s>"
            else:
                text = f"<s>[INST] {user_content} [/INST] {assistant_content}</s>"

            data.append({"text": text})
    return data


def main():
    print("=" * 60)
    print("RUNPOD: MISTRAL FINE-TUNING FOR BUSINESS VERIFICATION")
    print("=" * 60)
    print(f"Config: {CONFIG}")
    print()

    # Import after print so we see errors clearly
    try:
        from unsloth import FastLanguageModel
        from unsloth import is_bfloat16_supported
        from datasets import Dataset
        from trl import SFTTrainer
        from transformers import TrainingArguments
    except ImportError as e:
        print(f"\nMissing package: {e}")
        print("\nInstall with:")
        print("  pip install 'unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git'")
        print("  pip install --no-deps 'trl<0.9.0' peft accelerate bitsandbytes")
        sys.exit(1)

    # Find training file
    train_files = list(Path(".").glob("balanced_*.jsonl")) + list(Path(".").glob("**/balanced_*.jsonl"))
    if not train_files:
        print("ERROR: No balanced_*.jsonl training file found!")
        print("Upload balanced_all_20251209_101213.jsonl to the same directory")
        sys.exit(1)

    train_file = train_files[0]
    print(f"Using training file: {train_file}")

    # Load data
    print("Loading training data...")
    train_data = load_training_data(str(train_file))
    print(f"Loaded {len(train_data)} training samples")

    # Verify balance
    true_count = sum(1 for d in train_data if '"legitimate": true' in d['text'])
    false_count = sum(1 for d in train_data if '"legitimate": false' in d['text'])
    print(f"Data balance: {true_count} TRUE / {false_count} FALSE")

    if true_count == 0 or false_count == 0:
        print("WARNING: Data is not balanced! This may cause training issues.")

    # Create dataset
    dataset = Dataset.from_list(train_data)

    # Load model
    print(f"\nLoading model: {CONFIG['model_name']}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=CONFIG["model_name"],
        max_seq_length=CONFIG["max_seq_length"],
        dtype=None,
        load_in_4bit=True,
    )

    # Add LoRA
    print("Adding LoRA adapters...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=CONFIG["lora_r"],
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                       "gate_proj", "up_proj", "down_proj"],
        lora_alpha=CONFIG["lora_alpha"],
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    # Calculate warmup
    total_steps = (len(dataset) // (CONFIG["batch_size"] * CONFIG["gradient_accumulation"])) * CONFIG["epochs"]
    warmup_steps = max(100, int(total_steps * CONFIG["warmup_ratio"]))

    print(f"\nTraining config:")
    print(f"  Total samples: {len(dataset)}")
    print(f"  Epochs: {CONFIG['epochs']}")
    print(f"  Batch size: {CONFIG['batch_size']} x {CONFIG['gradient_accumulation']} = {CONFIG['batch_size'] * CONFIG['gradient_accumulation']}")
    print(f"  Total steps: ~{total_steps}")
    print(f"  Warmup steps: {warmup_steps}")
    print(f"  Learning rate: {CONFIG['learning_rate']}")

    # Output directory
    output_dir = Path(CONFIG["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    # Training arguments
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        per_device_train_batch_size=CONFIG["batch_size"],
        gradient_accumulation_steps=CONFIG["gradient_accumulation"],
        warmup_steps=warmup_steps,
        num_train_epochs=CONFIG["epochs"],
        learning_rate=CONFIG["learning_rate"],
        fp16=not is_bfloat16_supported(),
        bf16=is_bfloat16_supported(),
        logging_steps=10,
        save_steps=500,
        save_total_limit=2,
        optim="adamw_8bit",
        seed=42,
    )

    # Trainer
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=CONFIG["max_seq_length"],
        args=training_args,
    )

    # Train
    print("\n" + "=" * 60)
    print("STARTING TRAINING")
    print("=" * 60)
    trainer.train()

    # Save LoRA model
    print("\nSaving LoRA model...")
    lora_path = output_dir / "lora_model"
    model.save_pretrained(str(lora_path))
    tokenizer.save_pretrained(str(lora_path))

    # Save GGUF for Ollama
    print("\nConverting to GGUF format...")
    model.save_pretrained_gguf(
        str(output_dir),
        tokenizer,
        quantization_method="q4_k_m"
    )

    # Create Modelfile
    modelfile_content = f"""FROM {output_dir}/unsloth.Q4_K_M.gguf

PARAMETER temperature 0.3
PARAMETER top_p 0.9
PARAMETER num_ctx 2048
PARAMETER repeat_penalty 1.1
PARAMETER stop "</s>"
PARAMETER stop "[INST]"

TEMPLATE \"\"\"<s>[INST] {{{{ .System }}}}

{{{{ .Prompt }}}} [/INST] {{{{ .Response }}</s>\"\"\"

SYSTEM \"\"\"You are a business verification assistant. Your task is to determine if a company is a legitimate service provider that offers exterior building and property cleaning services.

Target services include:
- Pressure washing / power washing
- Window cleaning
- Soft washing
- Roof cleaning
- Gutter cleaning
- Solar panel cleaning
- Fleet/truck washing
- Wood restoration / deck cleaning

Respond with a JSON object containing:
- legitimate: true/false
- confidence: 0.0-1.0
- services: detected service types
- quality_signals: positive indicators
- red_flags: concerns or issues\"\"\"
"""

    with open(output_dir / "Modelfile", 'w') as f:
        f.write(modelfile_content)

    print("\n" + "=" * 60)
    print("TRAINING COMPLETE!")
    print("=" * 60)
    print(f"\nOutput files in: {output_dir}")
    print(f"  - lora_model/     (LoRA adapters)")
    print(f"  - unsloth.Q4_K_M.gguf (Ollama model)")
    print(f"  - Modelfile       (Ollama config)")
    print()
    print("To use with Ollama locally:")
    print("  1. Download the output directory")
    print("  2. cd verification-mistral-output")
    print("  3. ollama create verification-mistral -f Modelfile")
    print("  4. ollama run verification-mistral")


if __name__ == "__main__":
    main()
