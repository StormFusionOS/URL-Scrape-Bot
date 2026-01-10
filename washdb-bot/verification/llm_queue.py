#!/usr/bin/env python3
"""
LLM Queue Client - connects to shared LLM service.

This module provides a client interface to the shared LLM service,
which processes requests from all workers through a central queue
for steady GPU utilization.

Usage:
    from verification.llm_queue import llm_generate

    response = llm_generate("Is the sky blue?", max_tokens=5)

Requires the LLM service to be running:
    python verification/llm_service.py
"""

import os
import json
import socket
import time
import logging
import threading
import requests
from typing import Optional, Dict, Any


# Configuration
SOCKET_PATH = os.getenv("LLM_SERVICE_SOCKET", "/tmp/llm_service.sock")
MODEL_NAME = os.getenv("OLLAMA_MODEL", "unified-washdb")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")

logger = logging.getLogger(__name__)


class LLMServiceClient:
    """
    Client for the shared LLM service.

    Maintains a persistent connection to the LLM service for efficient
    request/response handling.
    """

    def __init__(self, socket_path: str = SOCKET_PATH):
        self.socket_path = socket_path
        self._socket: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._request_counter = 0

    def _connect(self) -> bool:
        """Establish connection to LLM service."""
        try:
            if self._socket:
                try:
                    self._socket.close()
                except:
                    pass

            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._socket.connect(self.socket_path)
            self._socket.settimeout(60.0)
            return True
        except Exception as e:
            logger.debug(f"Failed to connect to LLM service: {e}")
            self._socket = None
            return False

    def _ensure_connected(self) -> bool:
        """Ensure we have a valid connection."""
        if self._socket is None:
            return self._connect()

        # Test connection with empty recv (will fail if disconnected)
        try:
            self._socket.setblocking(False)
            try:
                data = self._socket.recv(1, socket.MSG_PEEK)
                if not data:
                    # Connection closed by server
                    return self._connect()
            except BlockingIOError:
                pass  # No data available, connection is fine
            finally:
                self._socket.setblocking(True)
                self._socket.settimeout(60.0)
            return True
        except:
            return self._connect()

    def generate(self, prompt: str, max_tokens: int = 5, timeout: float = 30.0) -> str:
        """
        Send a request to the LLM service and wait for response.

        Args:
            prompt: The prompt to process
            max_tokens: Maximum tokens to generate
            timeout: Maximum time to wait for response

        Returns:
            Generated response text

        Raises:
            RuntimeError: If service is unavailable or request fails
        """
        with self._lock:
            # Generate unique request ID
            self._request_counter += 1
            request_id = f"{threading.current_thread().ident}_{self._request_counter}_{time.time_ns()}"

            # Ensure connection
            if not self._ensure_connected():
                raise RuntimeError("LLM service not available")

            # Send request
            request_data = json.dumps({
                'id': request_id,
                'prompt': prompt,
                'max_tokens': max_tokens
            }) + "\n"

            try:
                self._socket.sendall(request_data.encode('utf-8'))
            except Exception as e:
                # Retry once with reconnection
                if not self._connect():
                    raise RuntimeError(f"Failed to send request: {e}")
                self._socket.sendall(request_data.encode('utf-8'))

            # Read response (newline-delimited JSON)
            self._socket.settimeout(timeout)
            data = b""
            try:
                while True:
                    chunk = self._socket.recv(1)
                    if not chunk:
                        raise RuntimeError("Connection closed by server")
                    if chunk == b"\n":
                        break
                    data += chunk
            except socket.timeout:
                raise TimeoutError(f"Request timed out after {timeout}s")

            # Parse response
            try:
                response = json.loads(data.decode('utf-8'))
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid response: {e}")

            if not response.get('success'):
                raise RuntimeError(f"LLM error: {response.get('error', 'Unknown error')}")

            return response.get('response', '')

    def close(self):
        """Close the connection."""
        with self._lock:
            if self._socket:
                try:
                    self._socket.close()
                except:
                    pass
                self._socket = None


class DirectLLMClient:
    """
    Direct Ollama client - fallback when service is not available.

    Used when USE_LLM_QUEUE=false or service is not running.
    """

    def __init__(self, model_name: str = MODEL_NAME, api_url: str = OLLAMA_URL):
        self.model_name = model_name
        self.api_url = api_url

    def generate(self, prompt: str, max_tokens: int = 5, timeout: float = 30.0) -> str:
        """Generate directly via Ollama API."""
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "raw": True,  # CRITICAL: bypass Ollama template to use ChatML format
            "options": {
                "temperature": 0.1,
                "num_predict": max_tokens,
                "top_p": 0.85,
                "top_k": 40
            }
        }

        response = requests.post(
            self.api_url,
            json=payload,
            timeout=timeout
        )
        response.raise_for_status()

        result = response.json()
        return result.get("response", "").strip()


# Thread-local storage for client instances
_thread_local = threading.local()


def _get_client() -> LLMServiceClient:
    """Get thread-local client instance."""
    if not hasattr(_thread_local, 'client'):
        _thread_local.client = LLMServiceClient()
    return _thread_local.client


def _get_direct_client() -> DirectLLMClient:
    """Get thread-local direct client instance."""
    if not hasattr(_thread_local, 'direct_client'):
        _thread_local.direct_client = DirectLLMClient()
    return _thread_local.direct_client


def is_service_available() -> bool:
    """Check if the LLM service is available."""
    return os.path.exists(SOCKET_PATH)


def llm_generate(prompt: str, max_tokens: int = 5, timeout: float = 30.0) -> str:
    """
    Generate text using the LLM.

    Tries the shared LLM service first, falls back to direct Ollama call
    if service is not available.

    Args:
        prompt: The prompt to process
        max_tokens: Maximum tokens to generate
        timeout: Maximum time to wait

    Returns:
        Generated response text
    """
    # Try shared service first
    if is_service_available():
        try:
            client = _get_client()
            return client.generate(prompt, max_tokens, timeout)
        except Exception as e:
            logger.debug(f"Service call failed, falling back to direct: {e}")

    # Fall back to direct call
    direct_client = _get_direct_client()
    return direct_client.generate(prompt, max_tokens, timeout)


def llm_generate_raw(
    prompt: str,
    model: str = None,
    max_tokens: int = 400,
    timeout: float = 30.0
) -> str:
    """
    Generate text using a specific model directly via Ollama.

    This function bypasses the shared LLM service and calls Ollama directly,
    allowing specification of a custom model.

    Args:
        prompt: The prompt to process
        model: The model name to use (defaults to OLLAMA_MODEL env var)
        max_tokens: Maximum tokens to generate
        timeout: Maximum time to wait

    Returns:
        Generated response text
    """
    model_name = model or MODEL_NAME
    client = DirectLLMClient(model_name=model_name)
    return client.generate(prompt, max_tokens, timeout)


# Legacy compatibility - these functions existed in the old version
def get_llm_queue():
    """Legacy compatibility - returns a dummy object."""
    class DummyQueue:
        def get_stats(self):
            return {
                'total_requests': 0,
                'total_latency_ms': 0,
                'errors': 0,
                'started_at': None,
                'avg_latency_ms': 0,
                'queue_size': 0,
                'running': is_service_available()
            }

        def submit(self, prompt: str, max_tokens: int = 5, timeout: float = 30.0) -> str:
            return llm_generate(prompt, max_tokens, timeout)

    return DummyQueue()


def shutdown_llm_queue():
    """Legacy compatibility - no-op."""
    pass
