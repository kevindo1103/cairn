-- Frozen DDL from accepted core 0.1.0, main 5526443b0b4f2e6cdf10cbd37f6ccc87b9a69a99.
CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS checkpoints (
                    issue TEXT NOT NULL, scope TEXT NOT NULL, checkpoint TEXT NOT NULL,
                    base TEXT NOT NULL, head TEXT NOT NULL, revision INTEGER NOT NULL,
                    PRIMARY KEY(issue, scope));
                CREATE TABLE IF NOT EXISTS recipients (
                    task TEXT PRIMARY KEY, busy INTEGER NOT NULL DEFAULT 0,
                    active_event TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, dedupe_key TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL, digest TEXT NOT NULL,
                    target TEXT NOT NULL, state TEXT NOT NULL,
                    priority INTEGER NOT NULL, dependency TEXT REFERENCES events(id),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    needs_inspection INTEGER NOT NULL DEFAULT 0,
                    eligible_at REAL NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    delivery_token TEXT, delivery_owner TEXT, delivery_until REAL,
                    ack_deadline REAL, worker_token TEXT, worker_owner TEXT, worker_until REAL,
                    receipt TEXT, ack_evidence TEXT, result_evidence TEXT, reason TEXT);
                CREATE INDEX IF NOT EXISTS queue ON events(target, state, priority, created_at);
                CREATE TABLE IF NOT EXISTS history (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT REFERENCES events(id),
                    at REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS history_no_update BEFORE UPDATE ON history
                    BEGIN SELECT RAISE(ABORT, 'history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS history_no_delete BEFORE DELETE ON history
                    BEGIN SELECT RAISE(ABORT, 'history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS payload_immutable
                    BEFORE UPDATE OF id, dedupe_key, payload, digest, target, dependency ON events
                    BEGIN SELECT RAISE(ABORT, 'event identity is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS event_no_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'events are durable'); END;
