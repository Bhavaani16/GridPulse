"""Domain errors mapped onto the SPEC section 6 error body."""

from __future__ import annotations


class NotFoundError(Exception):
    def __init__(self, schedule_id: str) -> None:
        self.schedule_id = schedule_id
        super().__init__(f"unknown schedule_id {schedule_id}")


class InvalidStateError(Exception):
    def __init__(self, schedule_id: str, status: str, action: str) -> None:
        self.schedule_id = schedule_id
        self.status = status
        self.action = action
        super().__init__(f"cannot {action} a schedule in status {status}")
