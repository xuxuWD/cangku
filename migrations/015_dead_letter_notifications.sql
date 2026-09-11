ALTER TABLE workbench_dead_letters
    ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
