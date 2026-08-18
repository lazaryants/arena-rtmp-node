import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MonitoringNavigationTests(unittest.TestCase):
    def test_privileged_links_are_hidden_until_role_is_loaded(self):
        html = (PROJECT_ROOT / "web/index.html").read_text(
            encoding="utf-8",
        )
        self.assertIn('id="configurationNavLink"', html)
        self.assertIn('data-minimum-role="admin"', html)
        self.assertIn('id="restreamNavLink"', html)
        self.assertIn('data-minimum-role="operator"', html)
        self.assertGreaterEqual(html.count("hidden>"), 2)

    def test_navigation_uses_safe_session_metadata(self):
        script = (PROJECT_ROOT / "web/script.js").read_text(
            encoding="utf-8",
        )
        self.assertIn("async function refreshNavigationAccess()", script)
        self.assertIn("fetch('/api/session'", script)
        self.assertIn("operator: 1", script)
        self.assertIn("manager: 2", script)
        self.assertIn("admin: 3", script)
        self.assertIn("refreshNavigationAccess();", script)


if __name__ == "__main__":
    unittest.main()
