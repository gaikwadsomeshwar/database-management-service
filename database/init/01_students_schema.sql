-- State metadata schema initialized on each per-state SQL server alongside that state's dedicated student table.
CREATE TABLE IF NOT EXISTS state_metadata (
    state_code VARCHAR(64) NOT NULL,
    state_name VARCHAR(100) NOT NULL,
    census_2011_population BIGINT UNSIGNED NOT NULL,
    assumed_student_ratio DECIMAL(4, 3) NOT NULL,
    allocated_student_count INT UNSIGNED NOT NULL,
    PRIMARY KEY (state_code),
    UNIQUE KEY uq_state_metadata_name (state_name)
) ENGINE=InnoDB;
