#!/usr/bin/env python3
"""
LLM Scheduler - Time-based scheduling between verification and standardization

This scheduler manages GPU resources by running only one LLM service at a time:
- Verification (Mistral 7B) runs during configured hours (default: 6 AM - 6 PM)
- Standardization (Llama 3B) runs during off-hours (default: 6 PM - 6 AM)

Due to RTX 3060 12GB VRAM constraints, only one model can run at a time.
"""

import os
import sys
import subprocess
import time
import signal
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Configuration
CONFIG = {
    # Verification runs from 6 AM to 6 PM (day shift)
    'verification_start_hour': 6,
    'verification_end_hour': 18,

    # Models
    'verification_model': 'verification-mistral-proper',
    'standardization_model': 'standardization-mistral7b',

    # Service scripts
    'verification_script': 'scripts/verification_service.py',
    'standardization_script': 'scripts/standardization_service.py',

    # Check interval
    'check_interval_seconds': 300,  # 5 minutes

    # State file
    'state_file': 'data/scheduler_state.json'
}


class LLMScheduler:
    def __init__(self):
        self.shutdown_event = False
        self.current_service = None
        self.current_process = None
        self.venv_python = str(Path(__file__).parent.parent / 'venv' / 'bin' / 'python')

        os.makedirs('data', exist_ok=True)

        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        self.shutdown_event = True
        self.stop_current_service()

    def get_current_mode(self) -> str:
        """Determine which service should run based on time."""
        hour = datetime.now().hour

        if CONFIG['verification_start_hour'] <= hour < CONFIG['verification_end_hour']:
            return 'verification'
        else:
            return 'standardization'

    def get_next_switch_time(self) -> datetime:
        """Calculate when the next mode switch will occur."""
        now = datetime.now()
        hour = now.hour

        if CONFIG['verification_start_hour'] <= hour < CONFIG['verification_end_hour']:
            # Currently verification, will switch to standardization
            next_switch = now.replace(
                hour=CONFIG['verification_end_hour'],
                minute=0,
                second=0,
                microsecond=0
            )
        else:
            # Currently standardization, will switch to verification
            if hour >= CONFIG['verification_end_hour']:
                # After end, next verification is tomorrow morning
                next_switch = (now + timedelta(days=1)).replace(
                    hour=CONFIG['verification_start_hour'],
                    minute=0,
                    second=0,
                    microsecond=0
                )
            else:
                # Before start, next verification is this morning
                next_switch = now.replace(
                    hour=CONFIG['verification_start_hour'],
                    minute=0,
                    second=0,
                    microsecond=0
                )

        return next_switch

    def stop_ollama_model(self, model: str):
        """Stop a specific Ollama model to free VRAM."""
        try:
            subprocess.run(
                ['ollama', 'stop', model],
                capture_output=True,
                timeout=30
            )
            logger.info(f"Stopped Ollama model: {model}")
        except Exception as e:
            logger.debug(f"Could not stop model {model}: {e}")

    def preload_ollama_model(self, model: str):
        """Preload an Ollama model into VRAM."""
        try:
            # Run a simple query to load the model
            subprocess.run(
                ['ollama', 'run', model, '--', 'test'],
                capture_output=True,
                timeout=120,
                input=b''
            )
            logger.info(f"Preloaded Ollama model: {model}")
        except Exception as e:
            logger.warning(f"Could not preload model {model}: {e}")

    def stop_current_service(self):
        """Stop the currently running service."""
        if self.current_process:
            logger.info(f"Stopping {self.current_service} service...")
            try:
                self.current_process.terminate()
                self.current_process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.current_process.kill()
            except Exception as e:
                logger.error(f"Error stopping service: {e}")

            self.current_process = None

        # Stop the model to free VRAM
        if self.current_service == 'verification':
            self.stop_ollama_model(CONFIG['verification_model'])
        elif self.current_service == 'standardization':
            self.stop_ollama_model(CONFIG['standardization_model'])

        self.current_service = None

    def start_service(self, mode: str):
        """Start a service in the given mode."""
        if mode == 'verification':
            script = CONFIG['verification_script']
            model = CONFIG['verification_model']
            args = ['--workers', '4']
        else:
            script = CONFIG['standardization_script']
            model = CONFIG['standardization_model']
            args = ['--workers', '2']

        script_path = str(Path(__file__).parent.parent / script)

        # Preload the model
        logger.info(f"Preloading model {model}...")
        self.preload_ollama_model(model)

        # Start the service
        logger.info(f"Starting {mode} service...")
        self.current_process = subprocess.Popen(
            [self.venv_python, script_path] + args,
            cwd=str(Path(__file__).parent.parent)
        )
        self.current_service = mode

        logger.info(f"{mode.capitalize()} service started with PID {self.current_process.pid}")

    def save_state(self):
        """Save current scheduler state."""
        state = {
            'current_service': self.current_service,
            'last_update': datetime.now().isoformat(),
            'mode': self.get_current_mode(),
            'next_switch': self.get_next_switch_time().isoformat()
        }

        try:
            with open(CONFIG['state_file'], 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save state: {e}")

    def is_service_running(self) -> bool:
        """Check if the current service process is still running."""
        if self.current_process is None:
            return False

        return self.current_process.poll() is None

    def run(self):
        """Main scheduler loop."""
        logger.info("=" * 60)
        logger.info("LLM SCHEDULER STARTING")
        logger.info(f"Verification hours: {CONFIG['verification_start_hour']}:00 - {CONFIG['verification_end_hour']}:00")
        logger.info(f"Standardization hours: {CONFIG['verification_end_hour']}:00 - {CONFIG['verification_start_hour']}:00")
        logger.info("=" * 60)

        while not self.shutdown_event:
            try:
                target_mode = self.get_current_mode()
                next_switch = self.get_next_switch_time()

                # Check if we need to switch modes
                if self.current_service != target_mode:
                    logger.info(f"Mode switch: {self.current_service or 'none'} -> {target_mode}")

                    # Stop current service if running
                    if self.current_service:
                        self.stop_current_service()
                        time.sleep(5)  # Give VRAM time to free

                    # Start new service
                    self.start_service(target_mode)

                # Check if service crashed and needs restart
                if not self.is_service_running() and self.current_service:
                    logger.warning(f"{self.current_service} service died, restarting...")
                    self.current_service = None  # Clear so it gets restarted
                    continue

                # Save state
                self.save_state()

                # Log status
                time_to_switch = next_switch - datetime.now()
                logger.info(
                    f"Running: {self.current_service} | "
                    f"Next switch in: {time_to_switch.seconds // 3600}h {(time_to_switch.seconds % 3600) // 60}m"
                )

                # Wait for next check
                for _ in range(CONFIG['check_interval_seconds']):
                    if self.shutdown_event:
                        break
                    time.sleep(1)

            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                time.sleep(60)

        # Cleanup
        self.stop_current_service()
        logger.info("LLM SCHEDULER STOPPED")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='LLM Service Scheduler')
    parser.add_argument('--verification-start', type=int, default=6,
                       help='Hour to start verification (0-23)')
    parser.add_argument('--verification-end', type=int, default=18,
                       help='Hour to end verification (0-23)')
    args = parser.parse_args()

    CONFIG['verification_start_hour'] = args.verification_start
    CONFIG['verification_end_hour'] = args.verification_end

    scheduler = LLMScheduler()
    scheduler.run()


if __name__ == '__main__':
    main()
