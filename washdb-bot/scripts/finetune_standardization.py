#!/usr/bin/env python3
"""
Fine-tune the Standardization LLM (llama3.2:3b) for business name extraction.

This uses the Claude-annotated training data to improve the small LLM's
ability to extract business names from YellowPages entries.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
    DataCollatorForLanguageModeling,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from datasets import Dataset
import bitsandbytes as bnb


def load_training_data(data_dir: Path, max_samples: int = None):
    """Load all JSONL training files from the data directory."""
    samples = []
    
    for jsonl_file in data_dir.glob("*.jsonl"):
        print(f"Loading {jsonl_file.name}...")
        with open(jsonl_file, 'r') as f:
            for line in f:
                data = json.loads(line)
                samples.append({
                    'prompt': data['prompt'],
                    'completion': data['completion']
                })
    
    if max_samples and len(samples) > max_samples:
        import random
        random.shuffle(samples)
        samples = samples[:max_samples]
    
    print(f"Loaded {len(samples)} training samples")
    return samples


def format_for_training(sample, tokenizer):
    """Format a sample for causal LM training."""
    # Format: <prompt>\n<completion>
    text = f"{sample['prompt']}\n{sample['completion']}"
    return tokenizer(
        text,
        truncation=True,
        max_length=256,  # Short sequences for name extraction
        padding='max_length',
    )


def main():
    parser = argparse.ArgumentParser(description='Fine-tune Standardization LLM')
    parser.add_argument('--epochs', type=int, default=3, help='Number of training epochs')
    parser.add_argument('--batch-size', type=int, default=4, help='Batch size')
    parser.add_argument('--max-samples', type=int, default=None, help='Max training samples')
    parser.add_argument('--lr', type=float, default=2e-4, help='Learning rate')
    args = parser.parse_args()
    
    # Paths
    data_dir = Path(__file__).parent.parent / "data" / "training"
    output_dir = Path(__file__).parent.parent / "models" / "standardization-llm-finetuned"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=== Standardization LLM Fine-tuning ===")
    print(f"Epochs: {args.epochs}")
    print(f"Batch size: {args.batch_size}")
    print(f"Learning rate: {args.lr}")
    print(f"Output: {output_dir}")
    print()
    
    # Load training data
    samples = load_training_data(data_dir, args.max_samples)
    if not samples:
        print("No training data found!")
        return
    
    # Load base model (llama3.2:3b equivalent from HuggingFace)
    model_name = "meta-llama/Llama-3.2-3B"
    
    # Check for local ollama model or use HF
    print(f"Loading model: {model_name}")
    
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    
    # Load with 4-bit quantization for memory efficiency
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        load_in_4bit=True,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True,
    )
    
    # Prepare for training
    model = prepare_model_for_kbit_training(model)
    
    # LoRA config for efficient fine-tuning
    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()
    
    # Prepare dataset
    print("Preparing dataset...")
    dataset = Dataset.from_list(samples)
    
    def tokenize_function(examples):
        texts = [f"{p}\n{c}" for p, c in zip(examples['prompt'], examples['completion'])]
        return tokenizer(texts, truncation=True, max_length=256, padding='max_length')
    
    tokenized_dataset = dataset.map(
        tokenize_function,
        batched=True,
        remove_columns=dataset.column_names
    )
    
    # Training arguments
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=4,
        learning_rate=args.lr,
        fp16=True,
        save_steps=100,
        logging_steps=10,
        save_total_limit=2,
        warmup_steps=50,
        lr_scheduler_type="cosine",
        report_to="none",
    )
    
    # Data collator
    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer,
        mlm=False,
    )
    
    # Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_dataset,
        data_collator=data_collator,
    )
    
    # Train
    print("\nStarting training...")
    trainer.train()
    
    # Save
    print(f"\nSaving model to {output_dir}")
    trainer.save_model()
    tokenizer.save_pretrained(output_dir)
    
    print("\n=== Training Complete ===")
    print(f"Model saved to: {output_dir}")
    print("\nTo convert to Ollama format, run:")
    print(f"  ollama create standardization-llm-ft -f {output_dir}/Modelfile")


if __name__ == "__main__":
    main()
