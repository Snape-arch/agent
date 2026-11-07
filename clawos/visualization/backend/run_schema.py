"""Migration 18: durable, per-Run change cursors for all database writers."""

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_changes (
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL, kind TEXT NOT NULL, item_key TEXT NOT NULL,
  PRIMARY KEY(run_id, revision)
);
CREATE INDEX IF NOT EXISTS runs_tenant_created_id ON runs(tenant_id, created_at DESC, id DESC);
CREATE TRIGGER IF NOT EXISTS runs_change AFTER UPDATE OF name,status,source,params,updated_at,error_message ON runs
BEGIN
  UPDATE runs SET revision=revision+1 WHERE id=NEW.id;
  INSERT INTO run_changes VALUES(NEW.id,(SELECT revision FROM runs WHERE id=NEW.id),'run',NEW.id);
END;
"""


def sqlite_schema() -> str:
    schema = SQLITE_SCHEMA
    for table, kind, key in (("metrics", "metric", "step"), ("events", "event", "id"), ("artifacts", "artifact", "id")):
        for operation in ("INSERT", "UPDATE", "DELETE"):
            row = "OLD" if operation == "DELETE" else "NEW"
            change_kind = kind + "-delete" if operation == "DELETE" else kind
            schema += f"""
CREATE TRIGGER IF NOT EXISTS {table}_change_{operation.lower()} AFTER {operation} ON {table}
BEGIN
  UPDATE runs SET revision=revision+1 WHERE id={row}.run_id;
  INSERT INTO run_changes SELECT {row}.run_id,revision,'{change_kind}',CAST({row}.{key} AS TEXT)
    FROM runs WHERE id={row}.run_id;
END;
"""
    return schema


def postgres_statements() -> list[str]:
    statements = [
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 0",
        "CREATE TABLE IF NOT EXISTS run_changes (run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,revision BIGINT NOT NULL,kind TEXT NOT NULL,item_key TEXT NOT NULL,PRIMARY KEY(run_id,revision))",
        "CREATE INDEX IF NOT EXISTS runs_tenant_created_id ON runs(tenant_id,created_at DESC,id DESC)",
        """CREATE OR REPLACE FUNCTION clawvision_run_change() RETURNS TRIGGER AS $$
DECLARE owner_id TEXT; next_revision BIGINT; item_key TEXT; change_kind TEXT;
BEGIN
  IF TG_TABLE_NAME='runs' THEN
    owner_id:=NEW.id; item_key:=NEW.id; change_kind:='run';
  ELSE
    IF TG_OP='DELETE' THEN
      owner_id:=OLD.run_id;
      IF TG_TABLE_NAME='metrics' THEN item_key:=OLD.step::TEXT; ELSE item_key:=OLD.id::TEXT; END IF;
    ELSE
      owner_id:=NEW.run_id;
      IF TG_TABLE_NAME='metrics' THEN item_key:=NEW.step::TEXT; ELSE item_key:=NEW.id::TEXT; END IF;
    END IF;
    change_kind:=CASE TG_TABLE_NAME WHEN 'metrics' THEN 'metric' WHEN 'events' THEN 'event' ELSE 'artifact' END;
    IF TG_OP='DELETE' THEN change_kind:=change_kind||'-delete'; END IF;
  END IF;
  UPDATE runs SET revision=revision+1 WHERE id=owner_id RETURNING revision INTO next_revision;
  IF next_revision IS NOT NULL THEN
    INSERT INTO run_changes VALUES(owner_id,next_revision,change_kind,item_key);
  END IF;
  RETURN NULL;
END; $$ LANGUAGE plpgsql""",
        "DROP TRIGGER IF EXISTS runs_change ON runs",
        "CREATE TRIGGER runs_change AFTER UPDATE OF name,status,source,params,updated_at,error_message ON runs FOR EACH ROW EXECUTE FUNCTION clawvision_run_change()",
    ]
    for table in ("metrics", "events", "artifacts"):
        statements.extend([
            f"DROP TRIGGER IF EXISTS {table}_change ON {table}",
            f"CREATE TRIGGER {table}_change AFTER INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION clawvision_run_change()",
        ])
    return statements
