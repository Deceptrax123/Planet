CREATE TABLE IF NOT EXISTS lab_snapshot (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    revision INTEGER NOT NULL,
    payload TEXT NOT NULL
);
