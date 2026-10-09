"""Run the SUMO simulation with a database-backed adaptive scheduler."""

import argparse
import json
from pathlib import Path
import sys
import time
import uuid

import traci

from config.config import (
    AGING_POINTS_PER_SECOND,
    GUI_DELAY_MS,
    NETWORK_FILE,
    ROUTE_FILES,
    SIMULATION_END,
    STEP_LENGTH,
)
from src.analytics.metrics import queue_metrics, tripinfo_metrics
from src.controller.signal_controller import SignalController
from src.database.db import Database
from src.scheduler.policies import choose
from src.traffic_monitor import TrafficMonitor

SCHEDULERS = ("fixed", "fcfs", "round_robin", "priority_aging")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=sorted(ROUTE_FILES), default="light")
    parser.add_argument("--scheduler", choices=(*SCHEDULERS, "all", "best"), default="priority_aging",
                        help="Use one scheduler, compare all, or select the lowest-AWT prior result")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--duration", type=int, default=SIMULATION_END)
    parser.add_argument("--gui", action="store_true", help="Run with SUMO-GUI")
    parser.add_argument("--gui-delay", type=float, default=GUI_DELAY_MS,
                        help="SUMO-GUI delay between simulation steps in milliseconds (default: 500)")
    return parser.parse_args()


def run() -> int:
    args = parse_args()
    if args.duration <= 0:
        raise ValueError("Simulation duration must be positive")
    if args.gui_delay < 0:
        raise ValueError("GUI delay cannot be negative")
    if args.scheduler == "all":
        for scheduler in SCHEDULERS:
            _run_one(args, scheduler)
        return 0

    if args.scheduler == "best":
        db = Database()
        try:
            scheduler, mean_wait, run_count = db.best_scheduler_for(args.scenario, args.seed, args.duration)
        finally:
            db.close()
        selection = {
            "method": "lowest mean AWT from prior completed runs",
            "scenario": args.scenario,
            "seed": args.seed,
            "mean_waiting_time_sec": round(mean_wait, 3),
            "historical_runs_for_selected_scheduler": run_count,
        }
        _run_one(args, scheduler, selection)
        return 0

    _run_one(args, args.scheduler)
    return 0


def _run_one(args: argparse.Namespace, scheduler: str, selection: dict | None = None) -> None:
    route_file = ROUTE_FILES[args.scenario]
    # Keep each run's output separate; a still-open SUMO-GUI process may hold its file open.
    tripinfo_file = Path("outputs") / "reports" / (
        f"tripinfo_{args.scenario}_{scheduler}_{args.seed}_{uuid.uuid4().hex[:12]}.xml"
    )
    tripinfo_file.parent.mkdir(parents=True, exist_ok=True)
    sumo_binary = "sumo-gui" if args.gui else "sumo"
    command = [sumo_binary, "--net-file", str(NETWORK_FILE), "--route-files", str(route_file),
               "--seed", str(args.seed), "--end", str(args.duration), "--step-length", str(STEP_LENGTH),
               "--tripinfo-output", str(tripinfo_file), "--time-to-teleport", "-1",
               "--no-step-log", "true", "--duration-log.disable", "true"]
    if args.gui:
        command.extend(["--delay", str(args.gui_delay), "--start"])

    config = {"duration": args.duration, "step_length": STEP_LENGTH,
              "gui_delay_ms": args.gui_delay if args.gui else None,
              "green_policy": "10s + 2s per queued vehicle, bounded 10-30s",
              "yellow_seconds": 3, "all_red_seconds": 1,
              "type_priority": "truck > car > motorcycle",
              "aging_points_per_second": AGING_POINTS_PER_SECOND}
    if selection is not None:
        config["scheduler_selection"] = selection
    db = Database()
    run_id = db.create_run(args.scenario, scheduler, args.seed, config)
    db.set_active_run(run_id)
    monitor = TrafficMonitor(traci)
    queue_samples: list[list[int]] = []
    completed = False
    start_wall = time.monotonic()

    def decide(now: float, current_approach: str):
        approaches = db.read_latest_approaches()
        return choose(scheduler, approaches, current_approach,
                      controller.last_served, now, controller.rr_cursor)

    controller = None
    try:
        traci.start(command)
        controller = SignalController(traci, scheduler, run_id, db, decide)
        while traci.simulation.getTime() < args.duration:
            traci.simulationStep()
            now = float(traci.simulation.getTime())
            observations = monitor.collect()
            db.write_snapshots(run_id, now, observations)
            queue_samples.append([int(row["queue_length"]) for row in observations])
            controller.advance(now)

        actual_duration = float(traci.simulation.getTime())
        # SUMO closes and completes tripinfo XML when the TraCI connection is closed.
        traci.close()
        avg_wait, throughput = tripinfo_metrics(tripinfo_file)
        avg_queue, max_queue = queue_metrics(queue_samples)
        results = {
            "average_waiting_time_sec": round(avg_wait, 3),
            "average_queue_length": round(avg_queue, 3),
            "maximum_queue_length": max_queue,
            "throughput_vehicles": throughput,
            "phase_switches": db.count_green_transitions(run_id),
            "simulation_duration_sec": actual_duration,
        }
        db.write_results(run_id, results)
        db.finish_run(run_id, "completed")
        completed = True
        output = {"run_id": run_id, "scenario": args.scenario, "scheduler": scheduler,
                  "results": results, "wall_seconds": round(time.monotonic() - start_wall, 2)}
        if selection is not None:
            output["scheduler_selection"] = selection
        print(json.dumps(output, indent=2))
    finally:
        if traci.isLoaded():
            traci.close()
        if not completed:
            db.finish_run(run_id, "failed")
        db.close()


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(f"Run failed: {exc}", file=sys.stderr)
        raise
