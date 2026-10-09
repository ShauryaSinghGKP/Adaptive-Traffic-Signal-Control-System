from collections.abc import Sequence

from config.config import (
    AGING_POINTS_PER_SECOND,
    GREEN_BASE_SECONDS,
    GREEN_SECONDS_PER_QUEUED_VEHICLE,
    MAX_GREEN_SECONDS,
    MIN_GREEN_SECONDS,
    RR_QUANTUM_SECONDS,
)
from src.scheduler.models import ApproachState, Decision


def requested_green(queue_length: int) -> int:
    """Calculate a bounded green duration from queue size, not vehicle class."""
    raw = GREEN_BASE_SECONDS + GREEN_SECONDS_PER_QUEUED_VEHICLE * max(0, queue_length)
    return min(MAX_GREEN_SECONDS, max(MIN_GREEN_SECONDS, int(raw)))


def choose(mode: str, approaches: Sequence[ApproachState], current_approach: str | None,
           last_served: dict[str, float], now: float, rr_cursor: int) -> tuple[Decision, int]:
    """Pick one non-empty approach. Returns decision and updated RR cursor."""
    eligible = [approach for approach in approaches if approach.vehicle_count > 0]
    if not eligible:
        return Decision(None, "No queued vehicles", 0.0, MIN_GREEN_SECONDS), rr_cursor

    if mode == "fcfs":
        selected = max(eligible, key=lambda a: (a.oldest_waiting_time, a.direction))
        score = selected.oldest_waiting_time
        reason = "Oldest continuously observed queue"


    elif mode == "round_robin":
        selected_index = next(
            index for offset in range(len(approaches))
            for index in [(rr_cursor + offset) % len(approaches)]
            if approaches[index].vehicle_count > 0
        )
        selected = approaches[selected_index]
        rr_cursor = (selected_index + 1) % len(approaches)
        score = float(selected.queue_length)
        reason = "Next non-empty approach in round-robin order"


    elif mode == "priority_aging":
        def score_approach(a: ApproachState) -> float:
            base = 3 * a.trucks + 2 * a.cars + a.motorcycles + a.queue_length
            waited_since_service = max(0.0, now - last_served.get(a.direction, 0.0))
            aging_time = max(waited_since_service, a.oldest_waiting_time)
            return base + AGING_POINTS_PER_SECOND * aging_time
        selected = max(eligible, key=lambda a: (score_approach(a), a.direction))
        score = score_approach(selected)
        reason = "Vehicle-class demand plus queue-age and since-service aging"


    else:
        raise ValueError(f"Unknown adaptive scheduler: {mode}")

    green = RR_QUANTUM_SECONDS if mode == "round_robin" else requested_green(selected.queue_length)
    return Decision(selected.direction, reason, float(score), validate_green(green)), rr_cursor


def validate_green(seconds: int) -> int:
    """Keep scheduling output within the controller's configured safety bounds."""
    if not MIN_GREEN_SECONDS <= seconds <= MAX_GREEN_SECONDS:
        raise ValueError(f"Scheduler returned unsafe green duration: {seconds}")
    return seconds
