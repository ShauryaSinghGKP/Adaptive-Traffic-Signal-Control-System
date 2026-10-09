"""Read one traffic snapshot per incoming direction from SUMO via TraCI."""

from collections import Counter
from typing import Any

from config.config import APPROACH_EDGES


class TrafficMonitor:
    def __init__(self, traci_module: Any) -> None:
        self.traci = traci_module
        self.queue_started: dict[str, float | None] = {direction: None for direction in APPROACH_EDGES}

    def collect(self) -> list[dict[str, Any]]:
        now = float(self.traci.simulation.getTime())
        rows = []
        for direction, edge_id in APPROACH_EDGES.items():
            lane_id = f"{edge_id}_0"
            vehicle_ids = self.traci.lane.getLastStepVehicleIDs(lane_id)
            type_counts: Counter[str] = Counter()
            waits = []
            for vehicle_id in vehicle_ids:
                vehicle_class = self.traci.vehicle.getVehicleClass(vehicle_id)
                if vehicle_class in {"truck", "trailer"}:
                    kind = "truck"
                elif vehicle_class == "motorcycle":
                    kind = "motorcycle"
                elif vehicle_class in {"passenger", "private"}:
                    kind = "car"
                else:
                    kind = "other"
                type_counts[kind] += 1
                waits.append(float(self.traci.vehicle.getAccumulatedWaitingTime(vehicle_id)))

            queue_length = int(self.traci.lane.getLastStepHaltingNumber(lane_id))
            if queue_length and self.queue_started[direction] is None:
                self.queue_started[direction] = now
            elif not queue_length:
                self.queue_started[direction] = None
            oldest_waiting = now - self.queue_started[direction] if self.queue_started[direction] is not None else 0.0

            rows.append({
                "direction": direction,
                "lane_id": lane_id,
                "vehicle_count": len(vehicle_ids),
                "queue_length": queue_length,
                "average_waiting_time": sum(waits) / len(waits) if waits else 0.0,
                "oldest_waiting_time": oldest_waiting,
                "types": {kind: type_counts.get(kind, 0) for kind in
                          ("truck", "car", "motorcycle", "other")},
            })
        return rows
