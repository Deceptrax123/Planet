CREATE TABLE IF NOT EXISTS lab_daily_report (
    day TEXT PRIMARY KEY,
    closed INTEGER NOT NULL CHECK (closed IN (0, 1)),
    payload TEXT NOT NULL
);
