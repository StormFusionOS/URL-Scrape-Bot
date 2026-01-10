#!/usr/bin/env python3
"""
Unified Mistral-7B Fine-tuning Script for RunPod

This script fine-tunes Mistral-7B-Instruct on combined verification and standardization tasks
using QLoRA (4-bit quantization with LoRA adapters) for efficient training.

Requirements:
- RunPod GPU instance (A100 40GB recommended, A6000 48GB works)
- ~16GB VRAM minimum with 4-bit quantization
- Training data in ChatML format

Usage on RunPod:
1. Upload training data to /workspace/data/
2. Run: python train_unified_mistral.py
3. Model saved to /workspace/output/unified-washdb-mistral/
"""

import os
import json
import torch
from datetime import datetime
from pathlib import Path

# Install requirements if not present
def install_requirements():
    import subprocess
    packages = [
        "transformers>=4.36.0",
        "datasets>=2.16.0",
        "accelerate>=0.25.0",
        "peft>=0.7.0",
        "bitsandbytes>=0.41.0",
        "trl>=0.7.0",
        "wandb",
        "scipy",
    ]
    for pkg in packages:
        subprocess.run(["pip", "install", "-q", pkg], check=False)

try:
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
    )
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from datasets import load_dataset
    from trl import SFTTrainer
except ImportError:
    print("Installing required packages...")
    install_requirements()
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
    )
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from datasets import load_dataset
    from trl import SFTTrainer


# ============================================================
# CONFIGURATION
# ============================================================

class TrainingConfig:
    # Model
    base_model = "mistralai/Mistral-7B-Instruct-v0.2"

    # Paths - adjust for RunPod
    data_dir = Path("/workspace/data")
    output_dir = Path("/workspace/output/unified-washdb-mistral")
    train_file = data_dir / "combined_train.jsonl"  # 54,484 enriched + enhanced examples
    val_file = data_dir / "combined_val.jsonl"  # 6,054 validation examples

    # Training hyperparameters
    num_epochs = 3
    batch_size = 4                    # Per device batch size
    gradient_accumulation_steps = 4   # Effective batch = 4 * 4 = 16
    learning_rate = 2e-4
    max_seq_length = 2048
    warmup_ratio = 0.03

    # LoRA configuration
    lora_r = 64                       # LoRA rank
    lora_alpha = 128                  # LoRA alpha (usually 2x rank)
    lora_dropout = 0.05
    target_modules = [                # Modules to apply LoRA
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj"
    ]

    # Quantization
    use_4bit = True
    bnb_4bit_compute_dtype = torch.bfloat16
    bnb_4bit_quant_type = "nf4"
    use_double_quant = True

    # Logging
    logging_steps = 10
    eval_steps = 200
    save_steps = 500

    # Wandb (optional)
    use_wandb = True
    wandb_project = "washdb-unified-llm"
    wandb_run_name = f"unified-mistral-{datetime.now().strftime('%Y%m%d_%H%M')}"


config = TrainingConfig()


# ============================================================
# DATA LOADING
# ============================================================

def load_training_data():
    """Load training and validation datasets."""
    print(f"Loading training data from {config.train_file}")
    print(f"Loading validation data from {config.val_file}")

    # Load datasets
    train_dataset = load_dataset(
        "json",
        data_files=str(config.train_file),
        split="train"
    )

    val_dataset = load_dataset(
        "json",
        data_files=str(config.val_file),
        split="train"
    )

    print(f"Training examples: {len(train_dataset)}")
    print(f"Validation examples: {len(val_dataset)}")

    return train_dataset, val_dataset


def formatting_func(example):
    """Format example for training - just return the text field."""
    return example["text"]


# ============================================================
# MODEL SETUP
# ============================================================

def setup_model_and_tokenizer():
    """Initialize model with QLoRA configuration."""
    print(f"\nLoading base model: {config.base_model}")

    # Quantization config for 4-bit
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=config.use_4bit,
        bnb_4bit_quant_type=config.bnb_4bit_quant_type,
        bnb_4bit_compute_dtype=config.bnb_4bit_compute_dtype,
        bnb_4bit_use_double_quant=config.use_double_quant,
    )

    # Load model
    model = AutoModelForCausalLM.from_pretrained(
        config.base_model,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
    )

    # Prepare model for k-bit training
    model = prepare_model_for_kbit_training(model)

    # LoRA config
    lora_config = LoraConfig(
        r=config.lora_r,
        lora_alpha=config.lora_alpha,
        target_modules=config.target_modules,
        lora_dropout=config.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
    )

    # Apply LoRA
    model = get_peft_model(model, lora_config)

    # Print trainable parameters
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"Trainable parameters: {trainable_params:,} ({100 * trainable_params / total_params:.2f}%)")

    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        config.base_model,
        trust_remote_code=True,
    )
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    return model, tokenizer


# ============================================================
# TRAINING
# ============================================================

def train():
    """Main training function."""
    print("=" * 60)
    print("UNIFIED WASHDB LLM TRAINING")
    print("=" * 60)
    print(f"Start time: {datetime.now().isoformat()}")
    print()

    # Create output directory
    config.output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize wandb if enabled
    if config.use_wandb:
        try:
            import wandb
            wandb.init(
                project=config.wandb_project,
                name=config.wandb_run_name,
                config={
                    "base_model": config.base_model,
                    "lora_r": config.lora_r,
                    "lora_alpha": config.lora_alpha,
                    "learning_rate": config.learning_rate,
                    "batch_size": config.batch_size,
                    "epochs": config.num_epochs,
                }
            )
        except Exception as e:
            print(f"Wandb init failed: {e}")
            config.use_wandb = False

    # Load data
    train_dataset, val_dataset = load_training_data()

    # Setup model
    model, tokenizer = setup_model_and_tokenizer()

    # Training arguments
    training_args = TrainingArguments(
        output_dir=str(config.output_dir),
        num_train_epochs=config.num_epochs,
        per_device_train_batch_size=config.batch_size,
        per_device_eval_batch_size=config.batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        learning_rate=config.learning_rate,
        warmup_ratio=config.warmup_ratio,
        logging_steps=config.logging_steps,
        eval_strategy="steps",
        eval_steps=config.eval_steps,
        save_strategy="steps",
        save_steps=config.save_steps,
        save_total_limit=3,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        fp16=False,
        bf16=True,
        optim="paged_adamw_8bit",
        lr_scheduler_type="cosine",
        report_to="wandb" if config.use_wandb else "none",
        gradient_checkpointing=True,
        max_grad_norm=0.3,
    )

    # Initialize trainer
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        args=training_args,
        formatting_func=formatting_func,
        max_seq_length=config.max_seq_length,
        packing=False,
    )

    # Train
    print("\nStarting training...")
    trainer.train()

    # Save final model
    print("\nSaving final model...")
    final_model_path = config.output_dir / "final"
    trainer.save_model(str(final_model_path))
    tokenizer.save_pretrained(str(final_model_path))

    # Save training config
    config_path = config.output_dir / "training_config.json"
    with open(config_path, 'w') as f:
        json.dump({
            "base_model": config.base_model,
            "lora_r": config.lora_r,
            "lora_alpha": config.lora_alpha,
            "lora_dropout": config.lora_dropout,
            "target_modules": config.target_modules,
            "learning_rate": config.learning_rate,
            "batch_size": config.batch_size,
            "epochs": config.num_epochs,
            "max_seq_length": config.max_seq_length,
            "trained_at": datetime.now().isoformat(),
        }, f, indent=2)

    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)
    print(f"Model saved to: {final_model_path}")
    print(f"End time: {datetime.now().isoformat()}")

    if config.use_wandb:
        wandb.finish()


# ============================================================
# EXPORT TO GGUF (for Ollama)
# ============================================================

def merge_and_export():
    """Merge LoRA weights and export to GGUF format for Ollama."""
    print("\n" + "=" * 60)
    print("MERGING LORA WEIGHTS AND EXPORTING TO GGUF")
    print("=" * 60)

    from peft import PeftModel

    # Load base model (full precision for merging)
    print(f"Loading base model: {config.base_model}")
    base_model = AutoModelForCausalLM.from_pretrained(
        config.base_model,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True,
    )

    # Load LoRA adapter
    adapter_path = config.output_dir / "final"
    print(f"Loading LoRA adapter from: {adapter_path}")
    model = PeftModel.from_pretrained(base_model, str(adapter_path))

    # Merge LoRA weights
    print("Merging LoRA weights...")
    merged_model = model.merge_and_unload()

    # Save merged model
    merged_path = config.output_dir / "merged"
    merged_path.mkdir(exist_ok=True)
    print(f"Saving merged model to: {merged_path}")
    merged_model.save_pretrained(str(merged_path))

    # Save tokenizer
    tokenizer = AutoTokenizer.from_pretrained(config.base_model)
    tokenizer.save_pretrained(str(merged_path))

    print("\nMerged model saved!")
    print("\nTo convert to GGUF for Ollama, run:")
    print(f"  python llama.cpp/convert.py {merged_path} --outtype f16 --outfile unified-washdb.gguf")
    print("  ./llama.cpp/quantize unified-washdb.gguf unified-washdb-q4km.gguf Q4_K_M")
    print("\nThen create Ollama model:")
    print("  ollama create unified-washdb -f Modelfile")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", action="store_true", help="Merge and export to GGUF")
    args = parser.parse_args()

    if args.export:
        merge_and_export()
    else:
        train()
