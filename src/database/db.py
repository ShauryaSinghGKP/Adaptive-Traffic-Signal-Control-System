"""Parameterized MySQL access for the traffic-in-the-loop scheduler."""

import json
import os
from pathlib import Path
from typing import Any

import mysql.connector

from config.config import APPROACH_ORDER
from src.scheduler.models import ApproachState


def _load_local_env() -> None:
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"\''))


class Database:
    def __init__(self) -> None:
        _load_local_env()
        self.connection = mysql.connector.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "adaptive_traffic"),
            autocommit=False,
        )

    def close(self) -> None:
        self.connection.close()

    def create_run(self, scenario: str, scheduler: str, seed: int, config: dict[str, Any]) -> int:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "INSERT INTO simulation_runs (scenario,scheduler,random_seed,config_json) VALUES (%s,%s,%s,%s)",
                (scenario, scheduler, seed, json.dumps(config)),
            )
            self.connection.commit()
            return int(cursor.lastrowid)
        finally:
            cursor.close()

    def best_scheduler_for(self, scenario: str, seed: int, duration: int) -> tuple[str, float, int]:
        """Return the lowest-mean-AWT scheduler for completed matching evaluations."""
        schedulers = ("fixed", "fcfs", "round_robin", "priority_aging")
        placeholders = ",".join("%s" for _ in schedulers)
        cursor = self.connection.cursor()
        try:
            cursor.execute(f"""
                SELECT r.scheduler, AVG(p.average_waiting_time_sec) AS mean_wait,
                       COUNT(*) AS run_count
                FROM simulation_runs AS r
                JOIN performance_results AS p ON p.run_id = r.run_id
                WHERE r.scenario = %s AND r.random_seed = %s AND r.status = 'completed'
                  AND CAST(JSON_UNQUOTE(JSON_EXTRACT(r.config_json, '$.duration')) AS UNSIGNED) = %s
                  AND r.scheduler IN ({placeholders})
                GROUP BY r.scheduler
                ORDER BY mean_wait ASC, r.scheduler ASC
            """, (scenario, seed, duration, *schedulers))
            rows = cursor.fetchall()
            averages = {row[0]: (float(row[1]), int(row[2])) for row in rows}
            missing = [mode for mode in schedulers if mode not in averages]
            if missing:
                raise ValueError(
                    f"Cannot select the lowest-AWT scheduler for scenario '{scenario}', seed {seed}, "
                    f"duration {duration}; "
                    f"missing completed results for: {', '.join(missing)}. "
                    "Run --scheduler all for this scenario and seed first."
                )
            winner = rows[0][0]
            mean_wait, run_count = averages[winner]
            return winner, mean_wait, run_count
        finally:
            cursor.close()

    def write_snapshots(self, run_id: int, sim_time: float, rows: list[dict[str, Any]]) -> None:
        cursor = self.connection.cursor()
        try:
            for row in rows:
                cursor.execute(
                    """INSERT INTO traffic_snapshots
                    (run_id,simulation_time,direction,lane_id,vehicle_count,queue_length,average_waiting_time_sec,oldest_queue_age_sec)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (run_id, sim_time, row["direction"], row["lane_id"], row["vehicle_count"],
                     row["queue_length"], row["average_waiting_time"], row["oldest_waiting_time"]),
                )
                snapshot_id = int(cursor.lastrowid)
                cursor.executemany(
                    """INSERT INTO vehicle_type_counts
                    (snapshot_id,run_id,simulation_time,direction,vehicle_type,vehicle_count)
                    VALUES (%s,%s,%s,%s,%s,%s)""",
                    [(snapshot_id, run_id, sim_time, row["direction"], kind, count)
                     for kind, count in row["types"].items()],
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    def read_latest_approaches(self) -> list[ApproachState]:
        cursor = self.connection.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT ts.direction, ts.queue_length, ts.vehicle_count,
                       ts.average_waiting_time_sec, ts.oldest_queue_age_sec,
                       COALESCE(SUM(CASE WHEN vc.vehicle_type='truck' THEN vc.vehicle_count ELSE 0 END),0) trucks,
                       COALESCE(SUM(CASE WHEN vc.vehicle_type='car' THEN vc.vehicle_count ELSE 0 END),0) cars,
                       COALESCE(SUM(CASE WHEN vc.vehicle_type='motorcycle' THEN vc.vehicle_count ELSE 0 END),0) motorcycles
                FROM traffic_snapshots ts
                JOIN (SELECT direction, MAX(snapshot_id) snapshot_id
                      FROM traffic_snapshots WHERE run_id=%s GROUP BY direction) latest
                  ON latest.snapshot_id=ts.snapshot_id
                LEFT JOIN vehicle_type_counts vc ON vc.snapshot_id=ts.snapshot_id
                GROUP BY ts.snapshot_id, ts.direction, ts.queue_length, ts.vehicle_count, ts.average_waiting_time_sec, ts.oldest_queue_age_sec
                ORDER BY ts.direction
            """, (self._active_run_id,))
            states = {row["direction"]: row for row in cursor.fetchall()}
            return [
                ApproachState(
                    direction=direction,
                    queue_length=int(states[direction]["queue_length"]),
                    vehicle_count=int(states[direction]["vehicle_count"]),
                    oldest_waiting_time=float(states[direction]["oldest_queue_age_sec"]),
                    average_waiting_time=float(states[direction]["average_waiting_time_sec"]),
                    trucks=int(states[direction]["trucks"]),
                    cars=int(states[direction]["cars"]),
                    motorcycles=int(states[direction]["motorcycles"]),
                )
                for direction in APPROACH_ORDER if direction in states
            ]
        finally:
            cursor.close()

    def set_active_run(self, run_id: int) -> None:
        self._active_run_id = run_id

    def write_decision(self, run_id: int, now: float, mode: str, decision: Any, status: str) -> int:
        cursor = self.connection.cursor()
        try:
            cursor.execute("""INSERT INTO scheduling_decisions
                (run_id,decision_time,scheduler,selected_approach,reason,priority_score,requested_green_seconds,status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (run_id, now, mode, decision.selected_approach, decision.reason, decision.priority_score,
                 decision.requested_green_seconds, status))
            self.connection.commit()
            return int(cursor.lastrowid)
        finally:
            cursor.close()

    def write_signal_event(self, run_id: int, decision_id: int | None, now: float,
                           previous: str, new: str, event_type: str,
                           colors: dict[str, str], note: str) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute("""INSERT INTO signal_events
              (decision_id,run_id,simulation_time,previous_phase,new_phase,event_type,
               north_state,east_state,south_state,west_state,applied,note)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s)""",
              (decision_id, run_id, now, previous, new, event_type,
               colors["north"], colors["east"], colors["south"], colors["west"], note))
            self.connection.commit()
        finally:
            cursor.close()

    def finish_run(self, run_id: int, status: str) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute("UPDATE simulation_runs SET status=%s, ended_at=CURRENT_TIMESTAMP WHERE run_id=%s",
                           (status, run_id))
            self.connection.commit()
        finally:
            cursor.close()

    def update_decision_status(self, decision_id: int | None, status: str) -> None:
        if decision_id is None:
            raise ValueError("Cannot update a missing decision")
        cursor = self.connection.cursor()
        try:
            cursor.execute("UPDATE scheduling_decisions SET status=%s WHERE decision_id=%s", (status, decision_id))
            self.connection.commit()
        finally:
            cursor.close()

    def count_green_transitions(self, run_id: int) -> int:
        cursor = self.connection.cursor()
        try:
            cursor.execute("""SELECT COUNT(*) FROM signal_events
                WHERE run_id=%s AND event_type='green' AND event_id > (
                    SELECT COALESCE(MIN(event_id),0) FROM signal_events
                    WHERE run_id=%s AND event_type='green')""",
                (run_id, run_id))
            return int(cursor.fetchone()[0])
        finally:
            cursor.close()

    def write_results(self, run_id: int, result: dict[str, float | int]) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute("""INSERT INTO performance_results
                (run_id,average_waiting_time_sec,average_queue_length,maximum_queue_length,
                 throughput_vehicles,phase_switches,simulation_duration_sec)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (run_id, result["average_waiting_time_sec"], result["average_queue_length"],
                 result["maximum_queue_length"], result["throughput_vehicles"],
                 result["phase_switches"], result["simulation_duration_sec"]))
            self.connection.commit()
        finally:
            cursor.close()
