"""Small data types shared by the scheduling policies."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ApproachState:
    direction: str
    queue_length: int
    vehicle_count: int
    oldest_waiting_time: float
    average_waiting_time: float
    trucks: int
    cars: int
    motorcycles: int


@dataclass(frozen=True)
class Decision:
    selected_approach: str | None
    reason: str
    priority_score: float
    requested_green_seconds: int
