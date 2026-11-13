"""Cooperative cancellation at operation-owned safe progress checkpoints."""
from threading import Event


class OperationCancelled(InterruptedError):
    pass


class TaskControl:
    def __init__(self):
        self.event = Event()

    def cancel(self):
        self.event.set()

    def checkpoint(self, amount=0):
        # 100 means an operation has already published its result. A late cancel
        # must not hide that completed artifact or pretend it was rolled back.
        if amount < 100 and self.event.is_set():
            raise OperationCancelled('Operation cancelled; completed reports and decisions are kept')
