-- ChronoTwin schema (PostgreSQL + TimescaleDB)
-- Apply with: Get-Content backend\app\db\schema.sql | docker compose exec -T timescale psql -U twin -d chronotwin

CREATE TABLE IF NOT EXISTS readings (
    ts            timestamptz NOT NULL,
    sensor_id     text        NOT NULL,
    zone          text        NOT NULL DEFAULT 'Z0',
    kind          text        NOT NULL,
    value         double precision NOT NULL,
    trust         double precision NOT NULL DEFAULT 1.0
);
SELECT create_hypertable('readings', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS readings_sensor_ts ON readings (sensor_id, ts DESC);

CREATE TABLE IF NOT EXISTS reports (
    ts             timestamptz NOT NULL,
    id             text PRIMARY KEY,
    category       text NOT NULL,
    zone           text NOT NULL DEFAULT 'Z0',
    reporter_trust double precision NOT NULL DEFAULT 0.5,
    -- free text is stored here and never read by a model
    text           text
);
SELECT create_hypertable('reports', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS incidents (
    id          text PRIMARY KEY,
    ts          timestamptz NOT NULL DEFAULT now(),
    kind        text NOT NULL,
    severity    text NOT NULL,
    zone        text NOT NULL DEFAULT 'Z0',
    entity_ids  text[] NOT NULL DEFAULT '{}',
    title       text NOT NULL DEFAULT '',
    detail      text NOT NULL DEFAULT '',
    priority    int  NOT NULL DEFAULT 5,
    trust       double precision NOT NULL DEFAULT 1.0,
    dedupe_key  text NOT NULL DEFAULT '',
    resolved    boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS incidents_open ON incidents (resolved, priority, ts DESC);

CREATE TABLE IF NOT EXISTS plans (
    id            text PRIMARY KEY,
    ts            timestamptz NOT NULL DEFAULT now(),
    status        text NOT NULL,
    version       int  NOT NULL DEFAULT 1,
    incident_ids  text[] NOT NULL DEFAULT '{}',
    summary       text NOT NULL DEFAULT '',
    actions_json  jsonb NOT NULL DEFAULT '[]',
    conflicts_json jsonb NOT NULL DEFAULT '[]',
    resolution    text NOT NULL DEFAULT '',
    critic_feedback text NOT NULL DEFAULT '',
    metrics_json  jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS action_log (
    ts        timestamptz NOT NULL DEFAULT now(),
    id        text PRIMARY KEY,
    plan_id   text NOT NULL DEFAULT '',
    action_id text NOT NULL DEFAULT '',
    tool      text NOT NULL,
    phase     text NOT NULL,
    actor     text NOT NULL DEFAULT 'agent',
    impact    text NOT NULL DEFAULT 'MEDIUM',
    ok        boolean NOT NULL DEFAULT true,
    detail    text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS action_log_plan ON action_log (plan_id, ts);

-- every agent tool call, for the "LLM calls scale with incidents" metric
CREATE TABLE IF NOT EXISTS llm_calls (
    ts          timestamptz NOT NULL DEFAULT now(),
    id          text PRIMARY KEY,
    agent       text NOT NULL,
    incident_id text NOT NULL DEFAULT '',
    kind        text NOT NULL DEFAULT 'complete',
    tokens_in   int NOT NULL DEFAULT 0,
    tokens_out  int NOT NULL DEFAULT 0,
    ok          boolean NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS llm_calls_agent ON llm_calls (agent, ts);
