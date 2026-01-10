#!/usr/bin/env python3
"""
LLM Scheduler - DEPRECATED

With the unified model (unified-washdb-v2), there's no longer a need to schedule
between verification and standardization models. A single model handles both
tasks simultaneously.

This file is kept for backwards compatibility but the scheduler is no longer
needed.

To use the unified model:
1. Ensure 'unified-washdb-v2' is loaded in Ollama: ollama run unified-washdb
2. Set OLLAMA_MODEL=unified-washdb in .env
3. Use verification.unified_llm for both verification and standardization

The unified model was trained on 60k+ examples and can handle both tasks
via different system prompts.
"""

import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    logger.warning("=" * 60)
    logger.warning("LLM SCHEDULER IS DEPRECATED")
    logger.warning("=" * 60)
    logger.warning("")
    logger.warning("With the unified model (unified-washdb-v2), scheduling between")
    logger.warning("verification and standardization is no longer needed.")
    logger.warning("")
    logger.warning("The same model handles both tasks simultaneously.")
    logger.warning("")
    logger.warning("To use the unified system:")
    logger.warning("  1. Load the model: ollama run unified-washdb-v2")
    logger.warning("  2. Set in .env: OLLAMA_MODEL=unified-washdb-v2")
    logger.warning("  3. Import: from verification.unified_llm import get_unified_llm")
    logger.warning("")
    logger.warning("Exiting - scheduler not needed.")
    logger.warning("=" * 60)
    sys.exit(0)


if __name__ == '__main__':
    main()
