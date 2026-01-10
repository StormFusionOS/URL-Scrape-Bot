# TRUTH_12: Unified LLM System

## Overview

The unified LLM system uses a single fine-tuned Mistral 7B model (`unified-washdb`) to handle both:
1. **Business Verification** - Determining if a company is a legitimate exterior cleaning service provider
2. **Name Standardization** - Extracting proper business names from website data

This replaces the previous multi-model approach that used separate models for each task.

## Model Details

- **Model Name**: `unified-washdb`
- **Base Model**: Mistral-7B-Instruct-v0.2
- **Training Data**: 60k+ examples (54k verification + 6k standardization)
- **Training Method**: QLoRA (4-bit quantization with LoRA adapters)
- **VRAM Usage**: ~8GB with 4-bit quantization

## Configuration

### Environment Variables

```bash
# .env
OLLAMA_MODEL=unified-washdb    # The unified model name
USE_LLM_QUEUE=true             # Use queue for steady GPU utilization
LLM_VERIFICATION_ENABLED=true  # Enable LLM verification
```

### Loading the Model

```bash
# After training, load the model into Ollama
ollama create unified-washdb -f Modelfile.unified
ollama run unified-washdb  # Test it's working
```

## Code Usage

### Primary Module

The main module is `verification/unified_llm.py`:

```python
from verification.unified_llm import get_unified_llm, UnifiedLLM

# Get singleton instance
llm = get_unified_llm()

# Verify a company
result = llm.verify_company(
    company_name="Pro Power Wash LLC",
    website="https://propowerwash.com",
    title="Pro Power Wash - Pressure Washing Services",
    homepage_text="We offer pressure washing, soft washing, and window cleaning...",
    services_text="Our services include residential and commercial pressure washing..."
)

# Result:
# {
#     'legitimate': True,
#     'confidence': 0.92,
#     'services': ['pressure_washing', 'soft_washing', 'window_cleaning'],
#     'reasoning': 'Clear exterior cleaning service provider with contact info',
#     'pressure_washing': True,
#     'window_cleaning': True,
#     'wood_restoration': False,
#     ...
# }

# Standardize a name
result = llm.standardize_name(
    current_name="Pro",  # Truncated name
    website="https://propowerwash.com",
    page_title="Pro Power Wash LLC | Home",
    og_site_name="Pro Power Wash",
    json_ld_name="Pro Power Wash LLC"
)

# Result:
# {
#     'name': 'Pro Power Wash LLC',
#     'confidence': 0.95,
#     'source': 'json_ld',
#     'success': True
# }
```

### Backwards Compatibility

Old imports still work via aliasing:

```python
# These all work and return the unified LLM
from scrape_site.trained_llm_verifier import get_trained_llm_verifier
from scrape_site.trained_llm_verifier import get_llm_verifier
from verification.unified_llm import get_llm_verifier
```

## System Prompts

The unified model uses different system prompts for each task:

### Verification Prompt
```
You are a business verification assistant. Analyze the company information and determine if this is a legitimate service provider offering exterior cleaning services.

Target services: Pressure washing, Window cleaning, Soft washing, Roof cleaning, Gutter cleaning, Solar panel cleaning, Fleet/truck washing, Wood restoration.

Respond with ONLY a valid JSON object:
{"legitimate": true/false, "confidence": 0.0-1.0, "services": [], "reasoning": "brief explanation"}
```

### Standardization Prompt
```
You are a business name extraction assistant. Extract the official business name from the provided website data.

Look for the name in order of reliability:
1. JSON-LD schema "name" field
2. og:site_name meta tag
3. Title tag (remove suffixes like "| Home")
4. H1 heading
5. Copyright notice

RULES:
- Return ONLY the business name
- Keep legal suffixes: LLC, Inc, Corp, Co.
- Fix to Title Case
- Remove taglines and slogans
- Keep location if part of name
- Return "UNKNOWN" if uncertain

Respond with JSON: {"name": "Business Name", "confidence": 0.0-1.0, "source": "where found"}
```

## Architecture

```
                    ┌─────────────────┐
                    │   unified-washdb │
                    │   (Mistral 7B)   │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
    ┌─────────▼─────────┐       ┌──────────▼──────────┐
    │   Verification    │       │   Standardization   │
    │   System Prompt   │       │   System Prompt     │
    └─────────┬─────────┘       └──────────┬──────────┘
              │                             │
    ┌─────────▼─────────┐       ┌──────────▼──────────┐
    │  verify_company() │       │ standardize_name()  │
    └───────────────────┘       └─────────────────────┘
```

## Queue Mode

When `USE_LLM_QUEUE=true`, requests go through a centralized queue:

```
Worker 1 ─┐
Worker 2 ─┼─► LLM Queue ─► Ollama API ─► unified-washdb
Worker 3 ─┘
```

Benefits:
- Steady GPU utilization
- No model loading/unloading
- Predictable throughput

## Migration from Old System

### Old System (Deprecated)
- `verification-mistral-proper` for verification
- `standardization-mistral7b` for name extraction
- `llm_scheduler.py` to switch between models

### New System
- Single `unified-washdb` model for both
- No scheduler needed
- Same GPU memory usage (4-bit quantization)

### Files Changed
| Old File | Status | New Location |
|----------|--------|--------------|
| `scrape_site/trained_llm_verifier.py` | Redirect | `verification/unified_llm.py` |
| `scrape_site/llm_verifier.py` | Deprecated | N/A |
| `scripts/llm_scheduler.py` | Deprecated | N/A |
| `scripts/name_extraction_service.py` | Use unified | `verification/unified_llm.py` |

## Troubleshooting

### Model Not Found
```bash
# Check if model exists
ollama list

# If not, create it from the trained model files
ollama create unified-washdb -f /path/to/Modelfile.unified
```

### VRAM Issues
The model uses ~8GB VRAM with 4-bit quantization. If you have less:
- Ensure no other models are loaded: `ollama ps`
- Stop other models: `ollama stop <model>`

### JSON Parse Errors
The model sometimes returns malformed JSON. The code handles this by:
1. Finding first `{` and last `}`
2. Parsing only that substring
3. Returning `None` if parsing fails

## Training

To retrain the unified model:

1. Prepare training data (verification + standardization examples)
2. Run on RunPod with A100 GPU:
   ```bash
   python train_unified_mistral.py
   ```
3. Export to GGUF for Ollama:
   ```bash
   python train_unified_mistral.py --export
   ```
4. Create Ollama model:
   ```bash
   ollama create unified-washdb -f Modelfile.unified
   ```

See `scripts/runpod_training/` for training scripts.
