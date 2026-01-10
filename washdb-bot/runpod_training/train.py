#!/usr/bin/env python3
"""
WashDB Unified Model Fine-Tuning Script for RunPod
Optimized for RTX 4090 / A100 with QLoRA
"""

import os
import sys
import json
import torch
import argparse
from datetime import datetime
from pathlib import Path

# Set environment variables before imports
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["WANDB_DISABLED"] = "true"  # Disable wandb unless you want it

from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq,
)
from peft import (
    LoraConfig,
    get_peft_model,
    prepare_model_for_kbit_training,
    TaskType,
)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Base model - Mistral 7B Instruct (good for chat/instruction following)
BASE_MODEL = "mistralai/Mistral-7B-Instruct-v0.2"

# Alternative models you can try:
# BASE_MODEL = "mistralai/Mistral-7B-v0.1"  # Base model without instruction tuning
# BASE_MODEL = "meta-llama/Llama-2-7b-chat-hf"  # Llama 2 chat

# QLoRA Configuration (BOOSTED for stronger training)
LORA_R = 128             # LoRA rank - higher = more capacity (boosted from 64)
LORA_ALPHA = 256         # LoRA alpha - typically 2x rank
LORA_DROPOUT = 0.05      # Dropout for regularization
LORA_TARGET_MODULES = [  # Which layers to apply LoRA to
    "q_proj",
    "k_proj", 
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
]

# Training Configuration (optimized for boosted LoRA)
MAX_SEQ_LENGTH = 1024    # Max sequence length (increase if you have longer examples)
BATCH_SIZE = 2           # Per-device batch size (reduced for higher LoRA rank)
GRADIENT_ACCUMULATION = 8  # Effective batch = BATCH_SIZE * GRADIENT_ACCUMULATION = 16
LEARNING_RATE = 1e-4     # Learning rate (lowered for stability with higher rank)
NUM_EPOCHS = 3           # Number of training epochs
WARMUP_RATIO = 0.03      # Warmup steps as ratio of total
WEIGHT_DECAY = 0.01      # Weight decay for regularization
SAVE_STEPS = 500         # Save checkpoint every N steps
LOGGING_STEPS = 50       # Log every N steps

# ============================================================================
# FUNCTIONS
# ============================================================================

def print_banner(text):
    """Print a banner."""
    print("\n" + "=" * 60)
    print(text)
    print("=" * 60)

def load_and_prepare_data(train_path, val_path, tokenizer):
    """Load and tokenize the dataset."""
    print_banner("LOADING DATASET")
    
    # Load JSONL files
    data_files = {"train": train_path}
    if val_path and Path(val_path).exists():
        data_files["validation"] = val_path
    
    dataset = load_dataset("json", data_files=data_files)
    
    print(f"Train examples: {len(dataset['train']):,}")
    if "validation" in dataset:
        print(f"Val examples: {len(dataset['validation']):,}")
    
    def tokenize_function(examples):
        """Tokenize examples."""
        # The 'text' field contains the full ChatML formatted conversation
        texts = examples["text"]
        
        # Tokenize
        tokenized = tokenizer(
            texts,
            truncation=True,
            max_length=MAX_SEQ_LENGTH,
            padding=False,
            return_tensors=None,
        )
        
        # For causal LM, labels = input_ids
        tokenized["labels"] = tokenized["input_ids"].copy()
        
        return tokenized
    
    print("\nTokenizing dataset...")
    tokenized_dataset = dataset.map(
        tokenize_function,
        batched=True,
        remove_columns=dataset["train"].column_names,
        desc="Tokenizing",
        num_proc=4,
    )
    
    # Print sample lengths
    sample_lengths = [len(x["input_ids"]) for x in tokenized_dataset["train"].select(range(min(1000, len(tokenized_dataset["train"]))))]
    print(f"Token lengths - Min: {min(sample_lengths)}, Max: {max(sample_lengths)}, Avg: {sum(sample_lengths)//len(sample_lengths)}")
    
    return tokenized_dataset

def setup_model_and_tokenizer(base_model):
    """Load model with QLoRA configuration."""
    print_banner("LOADING MODEL")
    
    print(f"Base model: {base_model}")
    print(f"Loading with 4-bit quantization...")
    
    # BitsAndBytes config for 4-bit quantization
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    
    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        base_model,
        trust_remote_code=True,
    )
    
    # Set padding token if not set
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        tokenizer.pad_token_id = tokenizer.eos_token_id
    
    # Ensure ChatML tokens are present
    special_tokens = ["<|im_start|>", "<|im_end|>"]
    tokens_to_add = [t for t in special_tokens if t not in tokenizer.get_vocab()]
    if tokens_to_add:
        print(f"Adding special tokens: {tokens_to_add}")
        tokenizer.add_special_tokens({"additional_special_tokens": tokens_to_add})
    
    # Load model
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
    )
    
    # Resize embeddings if we added tokens
    if tokens_to_add:
        model.resize_token_embeddings(len(tokenizer))
    
    # Prepare for k-bit training
    model = prepare_model_for_kbit_training(model)
    
    # LoRA configuration
    lora_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=LORA_TARGET_MODULES,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    
    # Apply LoRA
    model = get_peft_model(model, lora_config)
    
    # Print trainable parameters
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"\nTrainable parameters: {trainable_params:,} ({100 * trainable_params / total_params:.2f}%)")
    
    return model, tokenizer

def train(args):
    """Main training function."""
    print_banner("WASHDB MODEL FINE-TUNING")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
    
    # Setup model and tokenizer
    model, tokenizer = setup_model_and_tokenizer(args.base_model or BASE_MODEL)
    
    # Load data
    dataset = load_and_prepare_data(args.train_data, args.val_data, tokenizer)
    
    # Output directory
    output_dir = args.output_dir or f"./output/washdb-unified-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(output_dir, exist_ok=True)
    
    # Training arguments
    print_banner("TRAINING CONFIGURATION")
    
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=args.epochs or NUM_EPOCHS,
        per_device_train_batch_size=args.batch_size or BATCH_SIZE,
        per_device_eval_batch_size=args.batch_size or BATCH_SIZE,
        gradient_accumulation_steps=args.grad_accum or GRADIENT_ACCUMULATION,
        learning_rate=args.lr or LEARNING_RATE,
        weight_decay=WEIGHT_DECAY,
        warmup_ratio=WARMUP_RATIO,
        lr_scheduler_type="cosine",
        logging_steps=LOGGING_STEPS,
        save_steps=SAVE_STEPS,
        save_total_limit=3,
        evaluation_strategy="steps" if "validation" in dataset else "no",
        eval_steps=SAVE_STEPS if "validation" in dataset else None,
        bf16=True,
        tf32=True,
        gradient_checkpointing=True,
        optim="paged_adamw_8bit",
        max_grad_norm=0.3,
        group_by_length=True,
        report_to="none",
        dataloader_num_workers=4,
        remove_unused_columns=False,
    )
    
    print(f"Output dir: {output_dir}")
    print(f"Epochs: {training_args.num_train_epochs}")
    print(f"Batch size: {training_args.per_device_train_batch_size}")
    print(f"Gradient accumulation: {training_args.gradient_accumulation_steps}")
    print(f"Effective batch size: {training_args.per_device_train_batch_size * training_args.gradient_accumulation_steps}")
    print(f"Learning rate: {training_args.learning_rate}")
    
    # Data collator
    data_collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        padding=True,
        return_tensors="pt",
    )
    
    # Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset.get("validation"),
        data_collator=data_collator,
        tokenizer=tokenizer,
    )
    
    # Train!
    print_banner("STARTING TRAINING")
    print(f"Total optimization steps: {len(dataset['train']) // (training_args.per_device_train_batch_size * training_args.gradient_accumulation_steps) * training_args.num_train_epochs:,}")
    
    trainer.train()
    
    # Save final model
    print_banner("SAVING MODEL")
    final_path = os.path.join(output_dir, "final")
    trainer.save_model(final_path)
    tokenizer.save_pretrained(final_path)
    
    print(f"\nModel saved to: {final_path}")
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Save training info
    info = {
        "base_model": args.base_model or BASE_MODEL,
        "train_examples": len(dataset["train"]),
        "epochs": training_args.num_train_epochs,
        "batch_size": training_args.per_device_train_batch_size,
        "learning_rate": training_args.learning_rate,
        "lora_r": LORA_R,
        "lora_alpha": LORA_ALPHA,
        "completed_at": datetime.now().isoformat(),
    }
    with open(os.path.join(output_dir, "training_info.json"), "w") as f:
        json.dump(info, f, indent=2)
    
    return output_dir

def main():
    parser = argparse.ArgumentParser(description="Fine-tune WashDB model with QLoRA")
    parser.add_argument("--train-data", required=True, help="Path to training JSONL file")
    parser.add_argument("--val-data", default=None, help="Path to validation JSONL file")
    parser.add_argument("--base-model", default=None, help=f"Base model (default: {BASE_MODEL})")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    parser.add_argument("--epochs", type=int, default=None, help=f"Number of epochs (default: {NUM_EPOCHS})")
    parser.add_argument("--batch-size", type=int, default=None, help=f"Batch size (default: {BATCH_SIZE})")
    parser.add_argument("--grad-accum", type=int, default=None, help=f"Gradient accumulation (default: {GRADIENT_ACCUMULATION})")
    parser.add_argument("--lr", type=float, default=None, help=f"Learning rate (default: {LEARNING_RATE})")
    
    args = parser.parse_args()
    
    # Run training
    output_dir = train(args)
    
    print_banner("TRAINING COMPLETE")
    print(f"Your fine-tuned model is saved at: {output_dir}/final")
    print("\nTo use the model, you can merge the LoRA weights or load with PEFT.")

if __name__ == "__main__":
    main()
