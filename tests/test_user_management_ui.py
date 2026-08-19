import unittest
from pathlib import Path


class UserManagementUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.restream = (
            root / "app/templates/index.html"
        ).read_text(encoding="utf-8")
        cls.configuration = (
            root / "app/templates/config.html"
        ).read_text(encoding="utf-8")
        cls.users = (
            root / "app/templates/users.html"
        ).read_text(encoding="utf-8")
        cls.monitoring = (
            root / "web/index.html"
        ).read_text(encoding="utf-8")
        cls.monitoring_script = (
            root / "web/script.js"
        ).read_text(encoding="utf-8")
        cls.theme = (
            root / "app/templates/theme.css"
        ).read_text(encoding="utf-8")
        cls.monitoring_style = (
            root / "web/style.css"
        ).read_text(encoding="utf-8")

    def test_users_navigation_is_in_every_topbar(self):
        for page in (
            self.restream,
            self.configuration,
            self.users,
            self.monitoring,
        ):
            with self.subTest(page=page[:40]):
                header_end = page.index("</header>")
                users_link = page.index("Users")
                self.assertLess(users_link, header_end)

    def test_account_controls_are_in_topbar_not_page_heading(self):
        for page in (
            self.restream,
            self.configuration,
            self.users,
            self.monitoring,
        ):
            with self.subTest(page=page[:40]):
                header_end = page.index("</header>")
                account_slot = page.index('class="account-slot"')
                page_heading = page.index('class="page-heading')
                self.assertLess(account_slot, header_end)
                self.assertLess(header_end, page_heading)

    def test_reserved_account_width_and_navigation_slots_exist(self):
        for stylesheet in (self.theme, self.monitoring_style):
            self.assertIn(".account-slot", stylesheet)
            self.assertIn("width: 230px", stylesheet)
            self.assertIn(".topbar-actions", stylesheet)
        self.assertIn(".nav-placeholder", self.theme)
        self.assertIn(".nav-menu a[hidden]", self.monitoring_style)

    def test_monitoring_session_populates_account_area(self):
        self.assertIn('id="accountIdentity"', self.monitoring)
        self.assertIn('id="accountLogoutForm"', self.monitoring)
        self.assertIn('id="accountCsrfToken"', self.monitoring)
        self.assertIn("payload.username", self.monitoring_script)
        self.assertIn("payload.csrf_token", self.monitoring_script)

    def test_users_page_does_not_expose_hashes(self):
        self.assertNotIn("password_hash", self.users)
        self.assertIn("CURRENT_USERNAME", self.users)
        self.assertIn("You cannot disable", (
            Path(__file__).resolve().parents[1]
            / "app/restream_manager.py"
        ).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
