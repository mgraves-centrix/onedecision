-- Policy revision lineage. A revision never mutates the version it came from:
-- it creates a new candidate and points back, so the audit trail shows what a
-- human changed and what the agent originally proposed.
ALTER TABLE policies ADD COLUMN IF NOT EXISTS revised_from_policy_id TEXT;
ALTER TABLE policies ADD COLUMN IF NOT EXISTS revision_note TEXT;
