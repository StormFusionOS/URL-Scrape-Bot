#!/usr/bin/env python3
"""
LLM Verifier - DEPRECATED, use verification.unified_llm instead.

This module is kept for backwards compatibility only.
All functionality has been moved to the unified LLM module.
"""

import warnings
warnings.warn(
    "llm_verifier is deprecated. Use verification.unified_llm instead.",
    DeprecationWarning,
    stacklevel=2
)

# Redirect all imports to unified module
from verification.unified_llm import (
    UnifiedLLM as LLMVerifier,
    get_unified_llm as get_llm_verifier,
)

__all__ = ['LLMVerifier', 'get_llm_verifier']
