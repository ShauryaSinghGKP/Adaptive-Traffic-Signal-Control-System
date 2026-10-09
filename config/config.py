"""Project defaults. Values here are initial simulation parameters, not field timings."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMO_BINARY = "sumo"
SUMO_GUI_BINARY = "sumo-gui"
NETWORK_FILE = ROOT / "simulation/network/intersection.net.xml"
ROUTE_FILES = {
    "light": ROOT / "simulation/routes/light.rou.xml",
    "heavy": ROOT / "simulation/routes/heavy.rou.xml",
    "asymmetric": ROOT / "simulation/routes/asymmetric.rou.xml",
}
TRAFFIC_LIGHT_ID = "center"
SIMULATION_END = 400
STEP_LENGTH = 1.0
GUI_DELAY_MS = 500
MIN_GREEN_SECONDS = 10
MAX_GREEN_SECONDS = 30
GREEN_BASE_SECONDS = 10
GREEN_SECONDS_PER_QUEUED_VEHICLE = 2
YELLOW_SECONDS = 3
ALL_RED_SECONDS = 1
AGING_POINTS_PER_SECOND = 1.0
FIXED_GREEN_SECONDS = 30
RR_QUANTUM_SECONDS = 15
APPROACH_EDGES = {
    "north": "north_in",
    "east": "east_in",
    "south": "south_in",
    "west": "west_in",
}
APPROACH_ORDER = ("north", "east", "south", "west")
GREEN_PHASE = {"north": 0, "east": 3, "south": 6, "west": 9}
YELLOW_PHASE = {direction: phase + 1 for direction, phase in GREEN_PHASE.items()}
ALL_RED_PHASE = {direction: phase + 2 for direction, phase in GREEN_PHASE.items()}
