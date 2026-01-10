#!/usr/bin/env python3
"""
Trained LLM verifier - DEPRECATED, use verification.unified_llm instead.

This module is kept for backwards compatibility. All functionality has been
moved to the unified LLM module which handles both verification and
name standardization with a single model.

Import from here still works but redirects to the unified module.
"""

# Redirect all imports to unified module
from verification.unified_llm import (
    UnifiedLLM as TrainedLLMVerifier,
    get_unified_llm as get_trained_llm_verifier,
    get_unified_llm as get_llm_verifier,
)

__all__ = [
    'TrainedLLMVerifier',
    'get_trained_llm_verifier',
    'get_llm_verifier',
]
