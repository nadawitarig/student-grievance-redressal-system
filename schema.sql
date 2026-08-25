CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    student_id TEXT UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student'
        CHECK (role IN ('student', 'admin')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS grievances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_no TEXT NOT NULL UNIQUE,
    student_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL
        CHECK (category IN ('Academic', 'Facilities', 'Finance', 'Harassment', 'Hostel', 'Other')),
    description TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'medium'
        CHECK (priority IN ('low', 'medium', 'high')),
    status TEXT NOT NULL DEFAULT 'submitted'
        CHECK (status IN ('submitted', 'in_review', 'resolved', 'rejected')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS grievance_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grievance_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (grievance_id) REFERENCES grievances (id) ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_grievances_student_id ON grievances (student_id);
CREATE INDEX IF NOT EXISTS idx_grievances_status ON grievances (status);
CREATE INDEX IF NOT EXISTS idx_updates_grievance_id ON grievance_updates (grievance_id);
