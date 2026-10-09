"""Guard signal phase changes and configured timing bounds."""

from config.config import MAX_GREEN_SECONDS, MIN_GREEN_SECONDS


def validate_green(seconds: int) -> int:
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise TypeError("Green duration must be an integer number of seconds")
    if seconds < MIN_GREEN_SECONDS or seconds > MAX_GREEN_SECONDS:
        raise ValueError(f"Green duration must be between {MIN_GREEN_SECONDS} and {MAX_GREEN_SECONDS} seconds")
    return seconds


def validate_transition(stage: str, target_approach: str | None) -> None:
    if stage != "green":
        raise RuntimeError(f"Cannot request a phase transition while signal is in {stage}")
    if target_approach not in {"north", "east", "south", "west"}:
        raise ValueError(f"Invalid target approach: {target_approach}")
