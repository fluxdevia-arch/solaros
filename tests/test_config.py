from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from solar_crm import config


class DatabaseConfigurationTests(unittest.TestCase):
    def test_page_queries_do_not_use_single_quoted_sql_aliases(self):
        pages_dir = Path(__file__).resolve().parents[1] / "app_pages"
        invalid_alias = re.compile(r"\bAS\s+'[^']+'", re.IGNORECASE)

        offenders = [
            path.name
            for path in pages_dir.glob("*.py")
            if invalid_alias.search(path.read_text(encoding="utf-8"))
        ]

        self.assertEqual(offenders, [], "Use double quotes for PostgreSQL column aliases")

    def test_pages_do_not_order_by_unquoted_display_aliases(self):
        pages_dir = Path(__file__).resolve().parents[1] / "app_pages"
        invalid_order = re.compile(r"\bORDER\s+BY\s+(?!CASE\b)[A-ZÀ-Ý][\wÀ-ÿ]*")

        offenders = [
            path.name
            for path in pages_dir.glob("*.py")
            if invalid_order.search(path.read_text(encoding="utf-8"))
        ]

        self.assertEqual(offenders, [], "Quote display aliases or order by column position")

    def test_builds_encoded_postgres_url_from_separate_secrets(self):
        values = {
            "url": "",
            "host": "pooler.example.com",
            "user": "postgres.project",
            "password": "p@ss:/word",
            "name": "postgres",
            "port": 5432,
            "sslmode": "require",
        }

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            with patch.object(
                config,
                "_streamlit_secret",
                side_effect=lambda section, key: values.get(key),
            ):
                url = config.database_url()

        self.assertEqual(
            url,
            "postgresql://postgres.project:p%40ss%3A%2Fword@"
            "pooler.example.com:5432/postgres?sslmode=require",
        )

    def test_postgres_schema_translates_the_received_migration(self):
        from solar_crm.db import _postgres_schema

        migration = "CREATE TABLE sample (id INTEGER PRIMARY KEY AUTOINCREMENT, value REAL, photo BLOB);"
        translated = _postgres_schema(migration)

        self.assertIn("BIGSERIAL PRIMARY KEY", translated)
        self.assertIn("DOUBLE PRECISION", translated)
        self.assertIn("BYTEA", translated)
        self.assertIn("CREATE TABLE sample", translated)

    def test_postgres_connection_is_clean_before_returning_to_pool(self):
        from psycopg.pq import TransactionStatus

        from solar_crm import db

        wrapper = object.__new__(db.PostgresConnection)
        wrapper._pool = Mock()
        wrapper._connection = Mock()
        wrapper._connection.info.transaction_status = TransactionStatus.INTRANS

        connection = wrapper._connection
        wrapper.close()

        connection.rollback.assert_called_once_with()
        wrapper._pool.putconn.assert_called_once_with(connection)
        self.assertIsNone(wrapper._connection)


if __name__ == "__main__":
    unittest.main()
