CREATE TABLE IF NOT EXISTS workbench_accounts (
    account_id TEXT PRIMARY KEY,
    phone TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    position TEXT NOT NULL,
    full_name TEXT NOT NULL,
    email TEXT,
    role TEXT,
    tenant_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by TEXT,
    rejection_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_workbench_accounts_status
    ON workbench_accounts (status, requested_at DESC);
