"""Ollama Server Management.

Automatically starts and stops Ollama server when needed.
Only manages Ollama if we started it - doesn't interfere with
existing Ollama processes.
"""

from __future__ import annotations

import atexit
import signal
import subprocess
import sys
import time
from types import FrameType

from vibe.collaborative.ollama_detector import check_ollama_availability

OLLAMA_START_TIMEOUT = 5.0
OLLAMA_CHECK_INTERVAL = 0.5
PROCESS_TERM_TIMEOUT = 3.0


class OllamaManager:
    """Manages Ollama server lifecycle."""

    def __init__(self) -> None:
        self._ollama_process: subprocess.Popen[str] | None = None
        self._we_started_ollama = False
        self._cleanup_registered = False

    def ensure_ollama_running(self) -> tuple[bool, str]:
        """Ensure Ollama is running, starting it if necessary.

        Returns:
            Tuple of (success, message)
        """
        # Check if already running
        status = check_ollama_availability(timeout=1.0)

        if status.available:
            return True, "Ollama already running"

        # Try to start Ollama
        return self._start_ollama()

    def _start_ollama(self) -> tuple[bool, str]:
        """Start Ollama server as a background process.

        Returns:
            Tuple of (success, message)
        """
        try:
            # Check if ollama command exists
            result = subprocess.run(
                ["which", "ollama"], capture_output=True, text=True, timeout=2
            )

            if result.returncode != 0:
                return (
                    False,
                    "Ollama not installed. Install with: curl -fsSL https://ollama.ai/install.sh | sh",
                )

            # Start Ollama in the background
            # Redirect stdout/stderr to avoid polluting the terminal
            devnull = subprocess.DEVNULL

            self._ollama_process = subprocess.Popen(
                ["ollama", "serve"],
                stdout=devnull,
                stderr=devnull,
                start_new_session=True,  # Detach from parent process group
            )

            self._we_started_ollama = True

            # Register cleanup on exit
            if not self._cleanup_registered:
                atexit.register(self._cleanup)
                signal.signal(signal.SIGINT, self._signal_handler)
                signal.signal(signal.SIGTERM, self._signal_handler)
                self._cleanup_registered = True

            # Wait a bit for Ollama to start
            max_wait = OLLAMA_START_TIMEOUT
            wait_interval = OLLAMA_CHECK_INTERVAL
            elapsed = 0.0

            while elapsed < max_wait:
                time.sleep(wait_interval)
                elapsed += wait_interval

                status = check_ollama_availability(timeout=0.5)
                if status.available:
                    return True, "Ollama started successfully"

            # Timeout waiting for Ollama
            self._stop_ollama()
            return False, "Ollama failed to start within 5 seconds"

        except subprocess.TimeoutExpired:
            return False, "Timeout checking for Ollama installation"
        except Exception as e:
            return False, f"Failed to start Ollama: {e!s}"

    def _stop_ollama(self) -> None:
        """Stop Ollama if we started it."""
        if self._we_started_ollama and self._ollama_process:
            try:
                # Try graceful termination first
                self._ollama_process.terminate()

                # Wait up to 3 seconds for graceful shutdown
                try:
                    self._ollama_process.wait(timeout=PROCESS_TERM_TIMEOUT)
                except subprocess.TimeoutExpired:
                    # Force kill if it doesn't stop gracefully
                    self._ollama_process.kill()
                    self._ollama_process.wait()

            except Exception:
                # Ignore errors during cleanup
                pass
            finally:
                self._ollama_process = None
                self._we_started_ollama = False

    def _cleanup(self) -> None:
        """Cleanup handler called on exit."""
        self._stop_ollama()

    def _signal_handler(self, signum: int, frame: FrameType | None) -> None:
        """Handle termination signals."""
        self._cleanup()
        # Re-raise the signal to allow normal termination
        sys.exit(0)

    def is_managed_by_us(self) -> bool:
        """Check if we started and are managing Ollama."""
        return self._we_started_ollama


# Global instance
_manager: OllamaManager | None = None


def get_ollama_manager() -> OllamaManager:
    """Get the global OllamaManager instance."""
    global _manager
    if _manager is None:
        _manager = OllamaManager()
    return _manager


def ensure_ollama_running() -> tuple[bool, str]:
    """Ensure Ollama is running, starting it if needed.

    Returns:
        Tuple of (success, message)
    """
    return get_ollama_manager().ensure_ollama_running()


def cleanup_ollama() -> None:
    """Stop Ollama if we started it."""
    if _manager:
        _manager._cleanup()
