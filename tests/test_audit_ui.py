import unittest
from pathlib import Path


class AuditUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.pages = {
            "monitoring": (root / "web/index.html").read_text(
                encoding="utf-8"
            ),
            "restream": (
                root / "app/templates/index.html"
            ).read_text(encoding="utf-8"),
            "configuration": (
                root / "app/templates/config.html"
            ).read_text(encoding="utf-8"),
            "users": (
                root / "app/templates/users.html"
            ).read_text(encoding="utf-8"),
            "audit": (
                root / "app/templates/audit.html"
            ).read_text(encoding="utf-8"),
        }
        cls.theme = (
            root / "app/templates/theme.css"
        ).read_text(encoding="utf-8")
        cls.monitoring_style = (
            root / "web/style.css"
        ).read_text(encoding="utf-8")

    def test_audit_navigation_is_in_every_topbar(self):
        for name, page in self.pages.items():
            with self.subTest(page=name):
                header = page[:page.index("</header>")]
                self.assertIn("Audit", header)
                self.assertIn("/admin/audit/", header)

    def test_mobile_navigation_reserves_five_slots(self):
        self.assertIn(
            "grid-template-columns: repeat(5, 1fr)",
            self.theme,
        )
        self.assertIn(
            "grid-template-columns: repeat(5, 1fr)",
            self.monitoring_style,
        )

    def test_audit_page_uses_text_nodes_for_server_records(self):
        page = self.pages["audit"]
        self.assertIn("element.textContent = text", page)
        self.assertIn("body.replaceChildren()", page)
        self.assertNotIn("innerHTML", page)
        self.assertIn("/admin/api/audit", page)
        self.assertIn('id="sinceFilter"', page)
        self.assertIn('id="untilFilter"', page)
        self.assertIn("new Date(since).toISOString()", page)
        self.assertIn("window.setInterval(loadAudit, 15000)", page)


if __name__ == "__main__":
    unittest.main()
