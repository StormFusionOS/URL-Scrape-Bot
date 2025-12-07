#!/usr/bin/env python3
"""
Fine-tune Mistral 7B for business verification using Unsloth.

This script fine-tunes the Mistral model on Claude-verified business data
to create a local verification model that runs via Ollama.

Requirements:
    pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
    pip install --no-deps "trl<0.9.0" peft accelerate bitsandbytes

Usage:
    python scripts/finetune_mistral.py [--epochs 3] [--batch-size 4]
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime

# Find the latest training file
DATA_DIR = Path(__file__).parent.parent / "data" / "finetuning"
OUTPUT_DIR = Path(__file__).parent.parent / "models" / "verification-mistral"


def find_latest_training_file():
    """Find the most recent training JSONL file."""
    files = list(DATA_DIR.glob("train_verification_2*.jsonl"))
    if not files:
        print("Error: No training files found in", DATA_DIR)
        sys.exit(1)
    return max(files, key=lambda f: f.stat().st_mtime)


def load_training_data(filepath: Path) -> list:
    """Load training data from JSONL file using Mistral Instruct format."""
    data = []
    with open(filepath, 'r') as f:
        for line in f:
            record = json.loads(line.strip())
            messages = record.get('messages', [])

            # Extract system, user, and assistant content
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
            # <s>[INST] {system}\n\n{user} [/INST] {assistant}</s>
            if system_content:
                text = f"<s>[INST] {system_content}\n\n{user_content} [/INST] {assistant_content}</s>"
            else:
                text = f"<s>[INST] {user_content} [/INST] {assistant_content}</s>"

            data.append({"text": text})
    return data


def main():
    parser = argparse.ArgumentParser(description='Fine-tune Mistral for verification')
    parser.add_argument('--epochs', type=int, default=3, help='Number of training epochs')
    parser.add_argument('--batch-size', type=int, default=2, help='Batch size (reduce if OOM)')
    parser.add_argument('--max-samples', type=int, default=10000, help='Max training samples')
    parser.add_argument('--learning-rate', type=float, default=2e-4, help='Learning rate')
    args = parser.parse_args()

    print("=" * 60)
    print("MISTRAL FINE-TUNING FOR BUSINESS VERIFICATION")
    print("=" * 60)

    # Check for Unsloth
    try:
        from unsloth import FastLanguageModel
        from unsloth import is_bfloat16_supported
        from datasets import Dataset
        from trl import SFTTrainer
        from transformers import TrainingArguments
    except ImportError as e:
        print(f"\nError: Required package not installed: {e}")
        print("\nInstall with:")
        print('  pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"')
        print('  pip install --no-deps "trl<0.9.0" peft accelerate bitsandbytes')
        sys.exit(1)

    # Find training file
    train_file = find_latest_training_file()
    print(f"\nUsing training file: {train_file}")

    # Load data
    print("Loading training data...")
    train_data = load_training_data(train_file)

    # Limit samples if specified
    if args.max_samples and len(train_data) > args.max_samples:
        print(f"Limiting to {args.max_samples} samples (from {len(train_data)})")
        train_data = train_data[:args.max_samples]

    print(f"Training samples: {len(train_data)}")

    # Create HuggingFace dataset
    dataset = Dataset.from_list(train_data)

    # Load model with 4-bit quantization (fits in 12GB VRAM)
    print("\nLoading Mistral 7B with 4-bit quantization...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name="unsloth/mistral-7b-v0.3-bnb-4bit",
        max_seq_length=2048,
        dtype=None,  # Auto-detect
        load_in_4bit=True,
    )

    # Add LoRA adapters
    print("Adding LoRA adapters...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,  # LoRA rank
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                       "gate_proj", "up_proj", "down_proj"],
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    # Training arguments
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(OUTPUT_DIR),
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        num_train_epochs=args.epochs,
        learning_rate=args.learning_rate,
        fp16=not is_bfloat16_supported(),
        bf16=is_bfloat16_supported(),
        logging_steps=10,
        save_steps=500,
        save_total_limit=2,
        optim="adamw_8bit",
        seed=42,
    )

    # Create trainer
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=2048,
        args=training_args,
    )

    # Train
    print(f"\nStarting training for {args.epochs} epochs...")
    print(f"Batch size: {args.batch_size}, Learning rate: {args.learning_rate}")
    trainer.train()

    # Save model
    print("\nSaving fine-tuned model...")
    model.save_pretrained(OUTPUT_DIR / "lora_model")
    tokenizer.save_pretrained(OUTPUT_DIR / "lora_model")

    # Save to GGUF for Ollama
    print("\nConverting to GGUF format...")
    model.save_pretrained_gguf(
        str(OUTPUT_DIR),
        tokenizer,
        quantization_method="q4_k_m"  # Good balance of quality and size
    )

    # Create Modelfile for Ollama
    modelfile_path = OUTPUT_DIR / "Modelfile"
    with open(modelfile_path, 'w') as f:
        f.write(f"""FROM {OUTPUT_DIR}/unsloth.Q4_K_M.gguf

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
""")

    print("\n" + "=" * 60)
    print("FINE-TUNING COMPLETE")
    print("=" * 60)
    print(f"\nModel saved to: {OUTPUT_DIR}")
    print(f"\nTo import into Ollama:")
    print(f"  cd {OUTPUT_DIR}")
    print(f"  ollama create verification-mistral -f Modelfile")
    print(f"\nThen use with:")
    print(f"  ollama run verification-mistral")


if __name__ == '__main__':
    main()
