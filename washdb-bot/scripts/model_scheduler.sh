#!/bin/bash
# DEPRECATED - Model Scheduler is no longer needed
#
# With the unified model (unified-washdb), there's no need to switch between
# verification and standardization models. A single model handles both tasks.
#
# The unified model was trained on 60k+ examples and handles both verification
# and name standardization via different system prompts.
#
# To use the unified model:
#   1. Load it: ollama run unified-washdb
#   2. Set in .env: OLLAMA_MODEL=unified-washdb
#   3. Import: from verification.unified_llm import get_unified_llm

echo "========================================"
echo "MODEL SCHEDULER IS DEPRECATED"
echo "========================================"
echo ""
echo "The unified model (unified-washdb) handles both verification"
echo "and standardization. No scheduling needed."
echo ""
echo "Exiting."
exit 0
