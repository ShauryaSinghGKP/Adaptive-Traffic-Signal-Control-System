# Adaptive Traffic Signal Control System

Simulation-based PBL project connecting SUMO, TraCI, Python OS scheduling policies, and MySQL. The adaptive scheduler reads its live input from MySQL; Python then validates and applies its decision to SUMO through TraCI.

## Decision loop

```text
SUMO → TraCI monitor → MySQL traffic snapshots and vehicle type counts
                               ↓
                        Python reads latest SQL rows
                               ↓
                    FCFS / Round Robin / Priority + Aging
                               ↓
                decision saved to MySQL → safety controller
                               ↓
                 yellow → all-red → green through TraCI
                               ↓
                             SUMO
```

Traffic is recorded separately for North, East, South, and West. This version models left-hand traffic and gives exactly one approach green at a time; all other approaches show red. Each arm currently has a single straight-through movement so the exclusive approach phases are simple and easy to verify. The type-count table repeats the direction intentionally for easier inspection and mentor explanation.

## Scheduling and initial timing policy

- `fixed`: fixed 30-second green baseline.
- `fcfs`: serves the approach with the oldest continuously observed queue.
- `round_robin`: rotates among non-empty approaches with a 15-second quantum.
- `priority_aging`: scores type counts (truck weight 3, car weight 2, motorcycle weight 1), queue size, and aging based on the larger of oldest continuous queue age or time since last service. The initial aging factor is 1 priority point per second; tune it in `config/config.py` and compare with repeated runs.
- Adaptive FCFS and Priority + Aging request `10 + 2 × queued vehicles` seconds, clamped to 10–30 seconds. These are initial experimental values, not real-world signal engineering recommendations.
- Every approach change uses 3 seconds yellow and 1 second all-red. Exactly one approach is green at a time; the other three remain red. Python cannot bypass these stages.
- Vehicle classes are inputs to scheduling priority only. They do not get separate per-vehicle green intervals.

## Project layout

```text
config/                  Tunable paths and initial signal/scheduler parameters
simulation/network/      SUMO node, edge, and generated network files
simulation/routes/       Reproducible light, heavy, and asymmetric demand
src/main.py              Run orchestration and CLI
src/traffic_monitor.py   TraCI traffic and vehicle-class observations
src/scheduler/           SQL-fed state models and OS scheduling policies
src/controller/          Safety checks and SUMO phase transitions
src/database/            MySQL schema, queries, and transaction handling
src/analytics/           Metric calculations
data/                    Raw and exported experiment data
outputs/reports/         Trip info and report artifacts
```

## Setup

Requirements: Python 3.10+, SUMO 1.27+, MySQL 8+, and `netconvert` on `PATH`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create the MySQL schema (the account must be allowed to create the database):

```powershell
mysql -u root -p --execute="source src/database/schema.sql"
Copy-Item .env.example .env
```

If upgrading the database created by the earlier two-axis version, apply the one-time migration instead of recreating it: enter MySQL with `mysql -u root -p`, then run `SOURCE src/database/migrations/001_single_approach_scheduling.sql;`.

Set `DB_USER` and `DB_PASSWORD` in the local `.env`; `.env` is ignored by Git. Do not commit credentials. If schema creation is performed by an administrator, grant the configured account access to the `adaptive_traffic` database.

## Run

```powershell
python -m src.main --scenario light --scheduler priority_aging --seed 42
```

Choose `--scenario light|heavy|asymmetric`, `--scheduler fixed|fcfs|round_robin|priority_aging|all|best`, and optionally `--duration 400` or `--gui`. Selecting `all` runs the four schedulers sequentially against the same scenario, seed, and duration, creating a separate database run and results record for each scheduler. Selecting `best` looks at prior completed runs matching the same scenario, seed, and duration, requires results for all four schedulers, averages each scheduler's waiting-time result, and runs only the scheduler with the lowest mean AWT for the full simulation. It does not benchmark all four algorithms during the new run.

To choose the lowest-AWT scheduler from prior asymmetric seed-54 evaluations, then run only that scheduler in SUMO-GUI:

```powershell
python -m src.main --scenario asymmetric --scheduler best --seed 54 --gui --gui-delay 400
```

The selected scheduler is stored as the actual scheduler in `simulation_runs`; the selection method and historical mean AWT are stored in that run's `config_json`. To compare all four directly on heavy traffic:

```powershell
python -m src.main --scenario heavy --scheduler all --seed 43 --gui --gui-delay 500
```

SUMO-GUI runs default to a 500 ms delay per simulation step so signal and vehicles are visible; adjust with `--gui-delay 1000` (milliseconds) for slower viewing. Headless runs are unchanged. Runs use the same SUMO network, scenario routes, seed, and duration when comparing schedulers.

Each simulation step stores four directional snapshots and their type counts. The scheduler queries the latest SQL snapshots at green boundaries and records its decision before the controller proceeds through the safe phase transition. MySQL writes are parameterized and snapshot/type rows are committed as one transaction.

The checked-in `intersection.net.xml` can be regenerated with:

```powershell
netconvert --node-files simulation/network/intersection.nod.xml --edge-files simulation/network/intersection.edg.xml --connection-files simulation/network/intersection.con.xml --tllogic-files simulation/network/intersection.tll.xml --lefthand true --tls.default-type static --no-turnarounds true --output-file simulation/network/intersection.net.xml
```

## Tables

- `simulation_runs`: scenario, scheduler, seed, run status, and configuration.
- `traffic_snapshots`: direction/lane vehicle count, queue, average accumulated wait, and oldest continuous queue age.
- `vehicle_type_counts`: snapshot, run, simulation time, direction, class, and count.
- `scheduling_decisions`: scheduler output, score, requested green, and lifecycle status.
- `signal_events`: every directional light state during green/yellow/all-red transitions.
- `performance_results`: completed-trip waiting average, time-averaged queue, maximum queue, throughput, and phase switches.

Waiting-time result is SUMO tripinfo `waitingTime` averaged over completed trips. Average queue is the mean halting-vehicle count across four approaches and recorded steps. Maximum queue is the maximum halting count observed on any one approach. Throughput is completed trips by simulation end. Phase switches count entries into a new green phase, excluding initial green and green extensions.

## Validation

```powershell
python -m compileall -q config src
```

A real project run additionally requires the local MySQL credentials and schema above.
