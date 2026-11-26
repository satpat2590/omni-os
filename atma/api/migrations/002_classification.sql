-- Snapshot of the initial decision. Current membership always comes from task_tags.
ALTER TABLE tasks ADD COLUMN classification jsonb;
