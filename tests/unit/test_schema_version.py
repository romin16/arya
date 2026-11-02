from contextlib import asynccontextmanager

import psycopg
import pytest

from db.schema_version import CURRENT_SCHEMA_VERSION, ensure_schema_current


class FakeConnection:
    def __init__(self, *, version=None, error=None):
        self.version = version
        self.error = error

    async def execute(self, query):
        if self.error:
            raise self.error
        return self

    async def fetchone(self):
        return {"version": self.version}


class FakePool:
    def __init__(self, connection):
        self.fake_connection = connection

    @asynccontextmanager
    async def connection(self):
        yield self.fake_connection


@pytest.mark.asyncio
async def test_core_schema_guard_accepts_current_and_rejects_behind_database():
    await ensure_schema_current(FakePool(FakeConnection(version=CURRENT_SCHEMA_VERSION)))
    with pytest.raises(RuntimeError, match=r"behind the application .*python -m db.apply_schema"):
        await ensure_schema_current(FakePool(FakeConnection(version=CURRENT_SCHEMA_VERSION - 1)))


@pytest.mark.asyncio
async def test_core_schema_guard_explains_missing_version_table():
    with pytest.raises(RuntimeError, match="Database schema is not versioned.*python -m db.apply_schema"):
        await ensure_schema_current(FakePool(FakeConnection(error=psycopg.errors.UndefinedTable("missing"))))
