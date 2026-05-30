#!/usr/bin/env python3
import os
import sys

from sqlalchemy import inspect, text


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


FACTORY_COLUMNS = {
    "execution_runs": [
        ("workspace_id", "INTEGER"),
        ("work_packet_id", "INTEGER"),
        ("task_id", "INTEGER"),
        ("command", "TEXT"),
        ("prompt", "TEXT"),
        ("status", "VARCHAR(32)"),
        ("returncode", "INTEGER"),
        ("stdout", "TEXT"),
        ("stderr", "TEXT"),
        ("started_at", "TIMESTAMP WITH TIME ZONE"),
        ("finished_at", "TIMESTAMP WITH TIME ZONE"),
        ("duration_seconds", "DOUBLE PRECISION"),
        ("timeout_seconds", "INTEGER"),
        ("provider", "VARCHAR(64)"),
        ("model", "VARCHAR(255)"),
        ("input_tokens", "INTEGER"),
        ("output_tokens", "INTEGER"),
        ("total_tokens", "INTEGER"),
        ("estimated_cost_usd", "DOUBLE PRECISION"),
        ("error_message", "TEXT"),
    ],
    "execution_changed_files": [
        ("execution_run_id", "INTEGER"),
        ("file_path", "TEXT"),
        ("change_type", "VARCHAR(32)"),
        ("insertions", "INTEGER"),
        ("deletions", "INTEGER"),
        ("diff_summary", "TEXT"),
    ],
    "factory_events": [
        ("workspace_id", "INTEGER"),
        ("work_packet_id", "INTEGER"),
        ("task_id", "INTEGER"),
        ("execution_run_id", "INTEGER"),
        ("event_type", "VARCHAR(64)"),
        ("message", "TEXT"),
        ("payload_json", "TEXT"),
        ("created_at", "TIMESTAMP WITH TIME ZONE"),
    ],
    "work_packets": [
        ("workspace_id", "INTEGER"),
        ("title", "VARCHAR(255)"),
        ("risk_level", "VARCHAR(64)"),
        ("stop_condition", "TEXT"),
        ("estimated_minutes", "VARCHAR(64)"),
        ("status", "VARCHAR(32)"),
        ("trust_status", "VARCHAR(32)"),
        ("trust_level", "VARCHAR(32)"),
        ("trust_reason", "TEXT"),
        ("trust_reviewer", "VARCHAR(128)"),
        ("trust_notes", "TEXT"),
        ("readiness_status", "VARCHAR(32)"),
        ("readiness_checked_at", "TIMESTAMP WITH TIME ZONE"),
        ("readiness_checked_by", "VARCHAR(128)"),
        ("readiness_notes", "TEXT"),
        ("readiness_score", "INTEGER"),
        ("readiness_missing_items", "TEXT"),
        ("created_at", "TIMESTAMP WITH TIME ZONE"),
        ("started_at", "TIMESTAMP WITH TIME ZONE"),
        ("completed_at", "TIMESTAMP WITH TIME ZONE"),
        ("failed_at", "TIMESTAMP WITH TIME ZONE"),
        ("trusted_at", "TIMESTAMP WITH TIME ZONE"),
        ("revoked_at", "TIMESTAMP WITH TIME ZONE"),
    ],
    "work_packet_tasks": [
        ("work_packet_id", "INTEGER"),
        ("task_id", "INTEGER"),
        ("position", "INTEGER"),
        ("status", "VARCHAR(32)"),
        ("started_at", "TIMESTAMP WITH TIME ZONE"),
        ("completed_at", "TIMESTAMP WITH TIME ZONE"),
        ("failed_at", "TIMESTAMP WITH TIME ZONE"),
    ],
    "prompt_templates": [
        ("title", "VARCHAR(255)"),
        ("category", "VARCHAR(64)"),
        ("risk_level", "VARCHAR(64)"),
        ("description", "TEXT"),
        ("body", "TEXT"),
        ("variables_json", "TEXT"),
        ("tags_json", "TEXT"),
        ("status", "VARCHAR(32)"),
        ("success_count", "INTEGER"),
        ("failure_count", "INTEGER"),
        ("last_used_at", "TIMESTAMP WITH TIME ZONE"),
        ("created_at", "TIMESTAMP WITH TIME ZONE"),
        ("updated_at", "TIMESTAMP WITH TIME ZONE"),
    ],
    "orchestration_inbox_items": [
        ("workspace_id", "INTEGER"),
        ("title", "VARCHAR(255)"),
        ("raw_intent", "TEXT"),
        ("source", "VARCHAR(64)"),
        ("status", "VARCHAR(32)"),
        ("priority", "VARCHAR(32)"),
        ("category", "VARCHAR(64)"),
        ("triage_notes", "TEXT"),
        ("created_at", "TIMESTAMP WITH TIME ZONE"),
        ("updated_at", "TIMESTAMP WITH TIME ZONE"),
    ],
    "inbox_conversions": [
        ("workspace_id", "INTEGER"),
        ("inbox_item_id", "INTEGER"),
        ("target_type", "VARCHAR(32)"),
        ("target_id", "INTEGER"),
        ("conversion_status", "VARCHAR(32)"),
        ("conversion_notes", "TEXT"),
        ("operator_notes", "TEXT"),
        ("created_at", "TIMESTAMP WITH TIME ZONE"),
        ("updated_at", "TIMESTAMP WITH TIME ZONE"),
    ],
    "packet_prompt_drafts": [
        ("workspace_id", "INTEGER"),
        ("work_packet_id", "INTEGER"),
        ("inbox_item_id", "INTEGER"),
        ("source_type", "VARCHAR(64)"),
        ("source_id", "VARCHAR(128)"),
        ("template_id", "INTEGER"),
        ("title", "VARCHAR(255)"),
        ("draft_body", "TEXT"),
        ("category", "VARCHAR(64)"),
        ("safety_notes", "TEXT"),
        ("verification_notes", "TEXT"),
        ("status", "VARCHAR(32)"),
        ("created_at", "TIMESTAMP WITH TIME ZONE"),
        ("updated_at", "TIMESTAMP WITH TIME ZONE"),
    ],
    "operator_interventions": [
        ("workspace_id", "INTEGER"),
        ("title", "VARCHAR(255)"),
        ("details", "TEXT"),
        ("source_type", "VARCHAR(64)"),
        ("source_id", "VARCHAR(128)"),
        ("severity", "VARCHAR(32)"),
        ("status", "VARCHAR(32)"),
        ("category", "VARCHAR(64)"),
        ("recommended_action", "TEXT"),
        ("operator_notes", "TEXT"),
        ("context_json", "TEXT"),
        ("created_at", "TIMESTAMP WITH TIME ZONE"),
        ("updated_at", "TIMESTAMP WITH TIME ZONE"),
        ("acknowledged_at", "TIMESTAMP WITH TIME ZONE"),
        ("resolved_at", "TIMESTAMP WITH TIME ZONE"),
    ],
}


def quote_identifier(value):
    if not value.replace("_", "").isalnum():
        raise ValueError("Unsafe SQL identifier: {}".format(value))
    return '"{}"'.format(value)


def existing_columns(inspector, table_name):
    return set(column["name"] for column in inspector.get_columns(table_name))


def sync_postgresql_columns(engine, inspector):
    added = []
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table_name, columns in sorted(FACTORY_COLUMNS.items()):
            if table_name not in existing_tables:
                print("TABLE MISSING {}".format(table_name))
                continue

            print("TABLE EXISTS {}".format(table_name))
            present = existing_columns(inspector, table_name)
            for column_name, column_type in columns:
                if column_name in present:
                    print("COLUMN EXISTS {}.{}".format(table_name, column_name))
                    continue

                print("ADD COLUMN {}.{} {}".format(table_name, column_name, column_type))
                statement = "ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} {}".format(
                    quote_identifier(table_name),
                    quote_identifier(column_name),
                    column_type,
                )
                connection.execute(text(statement))
                added.append("{}.{}".format(table_name, column_name))
    return added


def main():
    try:
        from database import engine
        from models import Base
    except Exception as exception:
        print("FAILED import database setup: {}".format(exception))
        return 1

    try:
        print("DIALECT {}".format(engine.dialect.name))
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)
        if engine.dialect.name != "postgresql":
            print(
                "WARNING non-PostgreSQL dialect {}; create_all was run, no ALTER TABLE repair applied.".format(
                    engine.dialect.name
                )
            )
            return 0

        added = sync_postgresql_columns(engine, inspector)
        print("SYNC COMPLETE")
        if added:
            print("COLUMNS ADDED {}".format(", ".join(added)))
        else:
            print("COLUMNS ADDED none")
        return 0
    except Exception as exception:
        print("FAILED schema sync: {}".format(exception))
        return 1


if __name__ == "__main__":
    sys.exit(main())
