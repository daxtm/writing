"""Cooperative cancellation shared by the API client and draft operations.

Stop is a thread-safe flag checked at request/retry, stream-chunk and save
boundaries (ADR-0007). Cancelled is a distinct result: never retried, never
swallowed as an ordinary candidate failure.
"""

import threading


class Cancelled(Exception):
    """A cooperative Stop observed by the provider call or an operation."""


class CancellationToken:
    """Thread-safe flag owned by the caller (the GUI keeps exactly one)."""

    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    @property
    def cancelled(self):
        return self._event.is_set()

    def check(self):
        if self._event.is_set():
            raise Cancelled("stopped")

    def wait(self, timeout):
        """Interruptible wait: True when cancelled within timeout."""
        return self._event.wait(timeout)
