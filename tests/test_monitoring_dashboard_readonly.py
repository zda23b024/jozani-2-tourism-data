import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT_DIR / "monitoring_dashboard"
sys.path.insert(0, str(DASHBOARD_DIR))

from db import assert_select_only


class MonitoringDashboardReadOnlyTests(unittest.TestCase):
    def test_select_queries_are_allowed(self):
        assert_select_only("SELECT COUNT(*) FROM reviews")
        assert_select_only("WITH rows AS (SELECT 1) SELECT * FROM rows")

    def test_write_queries_are_blocked(self):
        blocked_queries = [
            "INSERT INTO reviews DEFAULT VALUES",
            "UPDATE reviews SET review_text = ''",
            "DELETE FROM reviews",
            "DROP TABLE reviews",
            "ALTER TABLE reviews ADD COLUMN demo TEXT",
            "CREATE TABLE demo (id bigint)",
        ]
        for query in blocked_queries:
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    assert_select_only(query)


if __name__ == "__main__":
    unittest.main()
