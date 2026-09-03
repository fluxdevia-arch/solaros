from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from solar_crm import config


class DatabaseConfigurationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
