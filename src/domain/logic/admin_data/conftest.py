"""Fixtures for the admin-data (Datasette) tests.

The saved queries read SQL views that exist only in the Alembic
migration, so these tests run against a migrated temp *file* DB
(`migrate_sqlite_file`), not the default in-memory `create_all` DB.
Rows are written through a sync SQLAlchemy session so the ORM handles
UUID / JSON / timestamp encoding exactly as the app does.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.domain.logic.admin_data.datasette_app import METADATA_PATH
from src.domain.logic.admin_data.sql_functions import register_sql_functions
from tests.helpers import migrate_sqlite_file


def days_ago(days: float) -> datetime:
    """A naive-UTC timestamp `days` ago, shaped like the app writes."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)


@pytest.fixture(scope="session")
def _migrated_template(tmp_path_factory) -> Path:
    """Run the migrations once per session; each test copies the file."""
    path = tmp_path_factory.mktemp("admin_data") / "template.db"
    migrate_sqlite_file(path)
    return path


@pytest.fixture
def admin_db(_migrated_template, tmp_path) -> Path:
    path = tmp_path / "admin.db"
    path.write_bytes(_migrated_template.read_bytes())
    return path


@pytest.fixture
def orm(admin_db) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{admin_db}")
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def run_query(admin_db):
    """Run a saved query from `metadata.yaml` by name, the way Datasette
    would: same SQL, same display functions, named params. Returns rows
    as dicts (column order preserved)."""
    queries = yaml.safe_load(METADATA_PATH.read_text())["databases"]["bedlam"][
        "queries"
    ]

    def _run(name: str, **params) -> list[dict]:
        conn = sqlite3.connect(admin_db)
        register_sql_functions(conn)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(queries[name]["sql"], params)
            rows = [dict(r) for r in cursor.fetchall()]
            conn.commit()
            return rows
        finally:
            conn.close()

    _run.queries = queries
    return _run
