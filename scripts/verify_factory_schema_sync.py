#!/usr/bin/env python3
import os
import sys

from sqlalchemy import inspect


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def fail(message):
    print("FAIL {}".format(message))
    return 1


def pass_line(message):
    print("PASS {}".format(message))


def table_columns(inspector, table_name):
    return set(column["name"] for column in inspector.get_columns(table_name))


def main():
    try:
        from database import engine
        from models import ExecutionRun, WorkPacket, WorkPacketTask
    except Exception as exception:
        return fail("imports failed: {}".format(exception))

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    required_tables = {"execution_runs", "factory_events", "execution_changed_files"}
    for table_name in sorted(required_tables):
        if table_name not in table_names:
            return fail("missing table {}".format(table_name))
        pass_line("table {} exists".format(table_name))

    if getattr(WorkPacket, "__tablename__", None):
        if "work_packets" not in table_names:
            return fail("missing table work_packets")
        pass_line("table work_packets exists")

    if getattr(WorkPacketTask, "__tablename__", None):
        if "work_packet_tasks" not in table_names:
            return fail("missing table work_packet_tasks")
        pass_line("table work_packet_tasks exists")

    execution_run_columns = table_columns(inspector, "execution_runs")
    required_execution_columns = {
        "status",
        "stdout",
        "stderr",
        "returncode",
        "total_tokens",
        "duration_seconds",
        "timeout_seconds",
    }
    missing = sorted(required_execution_columns - execution_run_columns)
    if missing:
        return fail("execution_runs missing columns: {}".format(", ".join(missing)))

    if "timeout_seconds" not in execution_run_columns:
        return fail("timeout_seconds missing")
    pass_line("execution_runs timeout_seconds exists")

    model_columns = set(column.name for column in ExecutionRun.__table__.columns)
    model_missing = sorted(required_execution_columns - model_columns)
    if model_missing:
        return fail("ExecutionRun model missing columns: {}".format(", ".join(model_missing)))
    pass_line("ExecutionRun model and database core columns match")
    pass_line("factory schema sync verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
