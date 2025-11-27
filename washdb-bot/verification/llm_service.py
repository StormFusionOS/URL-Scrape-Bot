#!/usr/bin/env python3
"""
Shared LLM Service for steady GPU utilization.

Runs as a separate process and accepts requests from all verification workers
via Unix socket. Processes requests back-to-back to keep GPU constantly busy.

Usage:
    python verification/llm_service.py

Workers connect via the socket at /tmp/llm_service.sock
"""

import os
import sys
import json
import socket
import signal
import threading
import queue
import time
import logging
import requests
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from runner.logging_setup import get_logger

# Configuration
SOCKET_PATH = os.getenv("LLM_SERVICE_SOCKET", "/tmp/llm_service.sock")
MODEL_NAME = os.getenv("OLLAMA_MODEL", "mistral:7b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
MAX_QUEUE_SIZE = 1000
IDLE_SLEEP = 0.01  # Very short sleep when queue empty

logger = get_logger("llm_service")

# Shutdown flag
shutdown_requested = False


@dataclass
class LLMRequest:
    """Request from a worker."""
    request_id: str
    prompt: str
    max_tokens: int
    connection: socket.socket
    received_at: float


class LLMService:
    """
    Shared LLM service with central request queue.

    Accepts connections from multiple workers, queues their requests,
    and processes them back-to-back for steady GPU utilization.
    """

    def __init__(self):
        self.model_name = MODEL_NAME
        self.ollama_url = OLLAMA_URL
        self.socket_path = SOCKET_PATH

        # Request queue
        self.request_queue: queue.Queue[LLMRequest] = queue.Queue(maxsize=MAX_QUEUE_SIZE)

        # Server socket
        self.server_socket: Optional[socket.socket] = None

        # Statistics
        self.stats = {
            'total_requests': 0,
            'total_latency_ms': 0,
            'errors': 0,
            'started_at': None,
            'connections': 0
        }

        # Threads
        self._processor_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """Start the LLM service."""
        global shutdown_requested
        shutdown_requested = False

        # Remove old socket file if exists
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        # Create server socket
        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(self.socket_path)
        self.server_socket.listen(50)  # Allow many pending connections
        self.server_socket.settimeout(1.0)  # Allow checking shutdown flag

        # Make socket accessible
        os.chmod(self.socket_path, 0o666)

        self._running = True
        self.stats['started_at'] = time.time()

        # Start processor thread
        self._processor_thread = threading.Thread(
            target=self._process_loop,
            name="LLMProcessor",
            daemon=True
        )
        self._processor_thread.start()

        logger.info("=" * 70)
        logger.info("LLM SERVICE STARTED")
        logger.info("=" * 70)
        logger.info(f"Socket: {self.socket_path}")
        logger.info(f"Model: {self.model_name}")
        logger.info(f"Ollama URL: {self.ollama_url}")
        logger.info("-" * 70)

        # Accept connections
        self._accept_loop()

    def _accept_loop(self):
        """Accept incoming connections from workers."""
        while self._running and not shutdown_requested:
            try:
                conn, _ = self.server_socket.accept()
                self.stats['connections'] += 1

                # Handle connection in a thread
                handler = threading.Thread(
                    target=self._handle_connection,
                    args=(conn,),
                    daemon=True
                )
                handler.start()

            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"Accept error: {e}")

        self._cleanup()

    def _handle_connection(self, conn: socket.socket):
        """Handle a single connection from a worker."""
        try:
            conn.settimeout(60.0)  # 60s timeout for long requests

            while self._running and not shutdown_requested:
                # Read request (newline-delimited JSON)
                data = b""
                while True:
                    chunk = conn.recv(1)
                    if not chunk:
                        return  # Connection closed
                    if chunk == b"\n":
                        break
                    data += chunk

                if not data:
                    continue

                try:
                    request_data = json.loads(data.decode('utf-8'))
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON: {e}")
                    continue

                # Create request
                request = LLMRequest(
                    request_id=request_data.get('id', ''),
                    prompt=request_data.get('prompt', ''),
                    max_tokens=request_data.get('max_tokens', 5),
                    connection=conn,
                    received_at=time.time()
                )

                # Queue the request
                try:
                    self.request_queue.put(request, timeout=5.0)
                except queue.Full:
                    # Send error response
                    error_response = json.dumps({
                        'id': request.request_id,
                        'response': '',
                        'error': 'Queue full',
                        'success': False
                    }) + "\n"
                    conn.sendall(error_response.encode('utf-8'))

        except socket.timeout:
            pass
        except Exception as e:
            logger.debug(f"Connection handler error: {e}")
        finally:
            try:
                conn.close()
            except:
                pass

    def _process_loop(self):
        """Main processing loop - processes requests back-to-back."""
        logger.info("Processor loop started")

        while self._running and not shutdown_requested:
            try:
                # Get request (short timeout to check flags)
                try:
                    request = self.request_queue.get(timeout=IDLE_SLEEP)
                except queue.Empty:
                    continue

                # Process immediately
                start_time = time.time()

                try:
                    response_text = self._call_ollama(request.prompt, request.max_tokens)
                    latency_ms = (time.time() - start_time) * 1000

                    response = {
                        'id': request.request_id,
                        'response': response_text,
                        'latency_ms': latency_ms,
                        'success': True
                    }

                    # Update stats
                    self.stats['total_requests'] += 1
                    self.stats['total_latency_ms'] += latency_ms

                except Exception as e:
                    latency_ms = (time.time() - start_time) * 1000
                    response = {
                        'id': request.request_id,
                        'response': '',
                        'latency_ms': latency_ms,
                        'success': False,
                        'error': str(e)
                    }
                    self.stats['errors'] += 1
                    logger.error(f"Ollama error: {e}")

                # Send response
                try:
                    response_data = json.dumps(response) + "\n"
                    request.connection.sendall(response_data.encode('utf-8'))
                except Exception as e:
                    logger.debug(f"Send response error: {e}")

                self.request_queue.task_done()

                # Log progress periodically
                if self.stats['total_requests'] % 100 == 0:
                    avg_latency = self.stats['total_latency_ms'] / self.stats['total_requests']
                    logger.info(
                        f"Progress: {self.stats['total_requests']} requests, "
                        f"avg latency: {avg_latency:.0f}ms, "
                        f"errors: {self.stats['errors']}, "
                        f"queue size: {self.request_queue.qsize()}"
                    )

            except Exception as e:
                logger.error(f"Processor loop error: {e}")
                time.sleep(0.1)

        logger.info("Processor loop stopped")

    def _call_ollama(self, prompt: str, max_tokens: int) -> str:
        """Call Ollama API."""
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": max_tokens,
                "top_p": 0.9,
                "top_k": 40
            }
        }

        response = requests.post(
            self.ollama_url,
            json=payload,
            timeout=15.0
        )
        response.raise_for_status()

        result = response.json()
        return result.get("response", "").strip()

    def _cleanup(self):
        """Clean up resources."""
        self._running = False

        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass

        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except:
                pass

        # Log final stats
        if self.stats['total_requests'] > 0:
            avg_latency = self.stats['total_latency_ms'] / self.stats['total_requests']
        else:
            avg_latency = 0

        runtime = time.time() - self.stats['started_at'] if self.stats['started_at'] else 0

        logger.info("=" * 70)
        logger.info("LLM SERVICE STOPPED")
        logger.info("=" * 70)
        logger.info(f"Runtime: {runtime/60:.1f} minutes")
        logger.info(f"Total requests: {self.stats['total_requests']}")
        logger.info(f"Average latency: {avg_latency:.0f}ms")
        logger.info(f"Errors: {self.stats['errors']}")
        logger.info(f"Connections handled: {self.stats['connections']}")


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global shutdown_requested
    shutdown_requested = True
    logger.info("Shutdown signal received")


def main():
    """Main entry point."""
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Start service
    service = LLMService()
    service.start()


if __name__ == '__main__':
    main()
