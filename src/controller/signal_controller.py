"""TraCI signal controller with explicit green -> yellow -> all-red -> green states."""

from typing import Any, Callable

from config.config import (
    APPROACH_ORDER,
    ALL_RED_PHASE,
    FIXED_GREEN_SECONDS,
    GREEN_PHASE,
    MIN_GREEN_SECONDS,
    TRAFFIC_LIGHT_ID,
    YELLOW_PHASE,
    YELLOW_SECONDS,
    ALL_RED_SECONDS,
)
from src.controller.safety import validate_green, validate_transition
from src.scheduler.models import Decision


def approach_colors(approach: str, color: str) -> dict[str, str]:
    """Return the complete intersection state; exactly one approach can be permissive."""
    return {direction: color if direction == approach else "red" for direction in APPROACH_ORDER}


def phase_name(approach: str, color: str) -> str:
    return f"{approach.title()}_{color.title()}"


class SignalController:
    def __init__(self, traci: Any, mode: str, run_id: int, db: Any,
                 decide: Callable[[float, str], tuple[Decision, int]], rr_cursor: int = 0) -> None:
        self.traci = traci
        self.mode = mode
        self.run_id = run_id
        self.db = db
        self.decide = decide
        self.rr_cursor = rr_cursor
        self.approach = "north"
        self.stage = "green"
        self.deadline = float(MIN_GREEN_SECONDS if mode != "fixed" else FIXED_GREEN_SECONDS)
        self.target_approach: str | None = None
        self.pending_decision_id: int | None = None
        self.pending_reason = "Initial SUMO phase"
        self.last_served = {direction: 0.0 for direction in APPROACH_ORDER}
        self.traci.trafficlight.setPhase(TRAFFIC_LIGHT_ID, GREEN_PHASE[self.approach])
        self.traci.trafficlight.setPhaseDuration(TRAFFIC_LIGHT_ID, self.deadline)
        self.db.write_signal_event(run_id, None, 0.0, "Startup", "North_Green", "green",
                                   approach_colors(self.approach, "green"), "Initial exclusive approach green")

    def advance(self, now: float) -> None:
        if now + 1e-9 < self.deadline:
            return
        if self.stage == "green":
            self._finish_green(now)
        elif self.stage == "yellow":
            self._enter_all_red(now)
        elif self.stage == "all_red":
            self._enter_next_green(now)
        else:
            raise RuntimeError(f"Unknown signal stage: {self.stage}")

    def _finish_green(self, now: float) -> None:
        if self.mode == "fixed":
            next_index = (APPROACH_ORDER.index(self.approach) + 1) % len(APPROACH_ORDER)
            target = APPROACH_ORDER[next_index]
            decision = Decision(target, "Fixed-time baseline cycle", 0.0, FIXED_GREEN_SECONDS)
            self.rr_cursor = 0
        else:
            decision, self.rr_cursor = self.decide(now, self.approach)
            target = decision.selected_approach
        if target is None:
            decision_id = self.db.write_decision(self.run_id, now, self.mode, decision, "no_traffic")
            self.db.write_signal_event(self.run_id, decision_id, now, phase_name(self.approach, "green"),
                                       phase_name(self.approach, "green"), "green_extension",
                                       approach_colors(self.approach, "green"),
                                       "No vehicles waiting; keep current safe green")
            duration = validate_green(FIXED_GREEN_SECONDS if self.mode == "fixed" else decision.requested_green_seconds)
            self.traci.trafficlight.setPhaseDuration(TRAFFIC_LIGHT_ID, duration)
            self.deadline = now + duration
            return

        validate_transition(self.stage, target)
        duration = validate_green(decision.requested_green_seconds)
        status = "applied" if target == self.approach else "pending"
        decision_id = self.db.write_decision(self.run_id, now, self.mode, decision, status)
        if target == self.approach:
            self.traci.trafficlight.setPhaseDuration(TRAFFIC_LIGHT_ID, duration)
            self.deadline = now + duration
            self.last_served[self.approach] = now
            self.db.write_signal_event(self.run_id, decision_id, now, phase_name(self.approach, "green"),
                                       phase_name(self.approach, "green"), "green_extension",
                                       approach_colors(self.approach, "green"),
                                       f"Continue selected approach for {duration} seconds")
            return

        self.pending_decision_id = decision_id
        self.target_approach = target
        self.pending_reason = decision.reason
        previous = phase_name(self.approach, "green")
        self.traci.trafficlight.setPhase(TRAFFIC_LIGHT_ID, YELLOW_PHASE[self.approach])
        self.traci.trafficlight.setPhaseDuration(TRAFFIC_LIGHT_ID, YELLOW_SECONDS)
        colors = approach_colors(self.approach, "yellow")
        self.db.write_signal_event(self.run_id, decision_id, now, previous, phase_name(self.approach, "yellow"),
                                   "yellow", colors, f"Ending green safely before {target}")
        self.stage = "yellow"
        self.deadline = now + YELLOW_SECONDS
        self._next_green_duration = duration

    def _enter_all_red(self, now: float) -> None:
        previous = phase_name(self.approach, "yellow")
        self.traci.trafficlight.setPhase(TRAFFIC_LIGHT_ID, ALL_RED_PHASE[self.approach])
        self.traci.trafficlight.setPhaseDuration(TRAFFIC_LIGHT_ID, ALL_RED_SECONDS)
        self.db.write_signal_event(self.run_id, self.pending_decision_id, now, previous, "All_Red",
                                   "all_red", {d: "red" for d in APPROACH_ORDER},
                                   "All-red clearance interval")
        self.stage = "all_red"
        self.deadline = now + ALL_RED_SECONDS

    def _enter_next_green(self, now: float) -> None:
        assert self.target_approach is not None
        previous_approach = self.approach
        self.approach = self.target_approach
        self.traci.trafficlight.setPhase(TRAFFIC_LIGHT_ID, GREEN_PHASE[self.approach])
        self.traci.trafficlight.setPhaseDuration(TRAFFIC_LIGHT_ID, self._next_green_duration)
        self.db.update_decision_status(self.pending_decision_id, "applied")
        self.db.write_signal_event(self.run_id, self.pending_decision_id, now, "All_Red",
                                   phase_name(self.approach, "green"), "green",
                                   approach_colors(self.approach, "green"),
                                   f"Selected after {self.pending_reason}")
        self.last_served[previous_approach] = now
        self.last_served[self.approach] = now
        self.stage = "green"
        self.deadline = now + self._next_green_duration
        self.target_approach = None
        self.pending_decision_id = None
