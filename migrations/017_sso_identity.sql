ALTER TABLE workbench_accounts
    ADD COLUMN IF NOT EXISTS sso_provider TEXT,
    ADD COLUMN IF NOT EXISTS sso_subject TEXT;

CREATE TABLE IF NOT EXISTS workbench_sso_states (
    state TEXT PRIMARY KEY,
    nonce TEXT NOT NULL,
    code_verifier TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workbench_sso_states_created
    ON workbench_sso_states (created_at);
