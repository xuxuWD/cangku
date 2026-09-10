ALTER TABLE workbench_accounts
    ADD COLUMN IF NOT EXISTS totp_secret TEXT,
    ADD COLUMN IF NOT EXISTS totp_confirmed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS totp_last_step BIGINT;
