CREATE DATABASE IF NOT EXISTS adaptive_traffic;
USE adaptive_traffic;

CREATE TABLE IF NOT EXISTS simulation_runs (
    run_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    scenario VARCHAR(40) NOT NULL,
    scheduler VARCHAR(40) NOT NULL,
    random_seed INT NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP NULL,
    status ENUM('running','completed','failed') NOT NULL DEFAULT 'running',
    config_json JSON NOT NULL,
    INDEX idx_run_comparison (scenario, scheduler, random_seed)
);
SELECT * FROM simulation_runs;
CREATE TABLE IF NOT EXISTS traffic_snapshots (
    snapshot_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id BIGINT NOT NULL,
    simulation_time DECIMAL(10,2) NOT NULL,
    direction ENUM('north','east','south','west') NOT NULL,
    lane_id VARCHAR(80) NOT NULL,
    vehicle_count INT UNSIGNED NOT NULL,
    queue_length INT UNSIGNED NOT NULL,
    average_waiting_time_sec DECIMAL(12,3) NOT NULL,
    oldest_queue_age_sec DECIMAL(12,3) NOT NULL,
    FOREIGN KEY (run_id) REFERENCES simulation_runs(run_id) ON DELETE CASCADE,
    UNIQUE KEY uq_run_time_lane (run_id, simulation_time, lane_id),
    INDEX idx_latest_direction (run_id, direction, simulation_time)
);
SELECT * FROM traffic_snapshots;
CREATE TABLE IF NOT EXISTS vehicle_type_counts (
    type_count_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    snapshot_id BIGINT NOT NULL,
    run_id BIGINT NOT NULL,
    simulation_time DECIMAL(10,2) NOT NULL,
    direction ENUM('north','east','south','west') NOT NULL,
    vehicle_type ENUM('truck','car','motorcycle','other') NOT NULL,
    vehicle_count INT UNSIGNED NOT NULL,
    FOREIGN KEY (snapshot_id) REFERENCES traffic_snapshots(snapshot_id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES simulation_runs(run_id) ON DELETE CASCADE,
    UNIQUE KEY uq_snapshot_type (snapshot_id, vehicle_type),
    INDEX idx_type_snapshot_time (run_id, simulation_time, direction)
);
SELECT * FROM vehicle_type_counts;
CREATE TABLE IF NOT EXISTS scheduling_decisions (
    decision_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id BIGINT NOT NULL,
    decision_time DECIMAL(10,2) NOT NULL,
    scheduler VARCHAR(40) NOT NULL,
    selected_approach ENUM('north','east','south','west') NULL,
    reason VARCHAR(255) NOT NULL,
    priority_score DECIMAL(12,3) NOT NULL,
    requested_green_seconds SMALLINT UNSIGNED NOT NULL,
    status ENUM('pending','applied','deferred','no_traffic') NOT NULL,
    FOREIGN KEY (run_id) REFERENCES simulation_runs(run_id) ON DELETE CASCADE,
    INDEX idx_decision_run_time (run_id, decision_time)
);
SELECT * FROM scheduling_decisions;
CREATE TABLE IF NOT EXISTS signal_events (
    event_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    decision_id BIGINT NULL,
    run_id BIGINT NOT NULL,
    simulation_time DECIMAL(10,2) NOT NULL,
    previous_phase VARCHAR(30) NOT NULL,
    new_phase VARCHAR(30) NOT NULL,
    event_type ENUM('green','green_extension','yellow','all_red') NOT NULL,
    north_state ENUM('red','yellow','green') NOT NULL,
    east_state ENUM('red','yellow','green') NOT NULL,
    south_state ENUM('red','yellow','green') NOT NULL,
    west_state ENUM('red','yellow','green') NOT NULL,
    applied BOOLEAN NOT NULL,
    note VARCHAR(255) NOT NULL,
    FOREIGN KEY (decision_id) REFERENCES scheduling_decisions(decision_id) ON DELETE SET NULL,
    FOREIGN KEY (run_id) REFERENCES simulation_runs(run_id) ON DELETE CASCADE,
    INDEX idx_signal_run_time (run_id, simulation_time)
);
SELECT * FROM signal_events;
CREATE TABLE IF NOT EXISTS performance_results (
    result_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id BIGINT NOT NULL UNIQUE,
    average_waiting_time_sec DECIMAL(12,3) NOT NULL,
    average_queue_length DECIMAL(12,3) NOT NULL,
    maximum_queue_length INT UNSIGNED NOT NULL,
    throughput_vehicles INT UNSIGNED NOT NULL,
    phase_switches INT UNSIGNED NOT NULL,
    simulation_duration_sec DECIMAL(12,3) NOT NULL,
    FOREIGN KEY (run_id) REFERENCES simulation_runs(run_id) ON DELETE CASCADE
);