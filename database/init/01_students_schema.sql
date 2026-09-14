-- This database contains generated data, so rebuild the table when reseeding.
DROP TABLE IF EXISTS students;

CREATE TABLE students (
    student_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    first_name VARCHAR(80) NOT NULL,
    last_name VARCHAR(80) NOT NULL,
    date_of_birth DATE NOT NULL,
    email VARCHAR(255) NOT NULL,
    phone_number VARCHAR(25) NOT NULL,
    city VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL,
    country VARCHAR(100) NOT NULL,
    enrollment_date DATE NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (student_id),
    UNIQUE KEY uq_students_email (email),
    KEY idx_students_last_name (last_name),
    KEY idx_students_enrollment_date (enrollment_date)
) ENGINE=InnoDB;
