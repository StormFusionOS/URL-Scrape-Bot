"""
Verification worker pool package.

Provides automated continuous verification of companies using a pool of worker processes.
"""

from .verification_worker_pool import VerificationWorkerPoolManager
from .verification_worker import run_worker

__all__ = ['VerificationWorkerPoolManager', 'run_worker']
