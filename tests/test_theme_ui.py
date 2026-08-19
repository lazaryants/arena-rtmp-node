import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
THEME_SCRIPT = PROJECT_ROOT / "web/theme.js"
THEME_STYLES = (
    PROJECT_ROOT / "web/style.css",
    PROJECT_ROOT / "app/templates/theme.css",
)
THEMED_PAGES = (
    PROJECT_ROOT / "web/index.html",
    PROJECT_ROOT / "app/templates/index.html",
    PROJECT_ROOT / "app/templates/config.html",
    PROJECT_ROOT / "app/templates/users.html",
    PROJECT_ROOT / "app/templates/audit.html",
    PROJECT_ROOT / "app/templates/login.html",
    PROJECT_ROOT / "app/templates/access_denied.html",
)


class ThemeUiTests(unittest.TestCase):
    def test_theme_is_loaded_before_page_styles(self):
        for path in THEMED_PAGES:
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                self.assertIn("theme.js?v=1", source)
                self.assertLess(
                    source.index("theme.js?v=1"),
                    source.index("<style") if "<style" in source else source.index("style.css"),
                )

    def test_theme_preference_is_persistent_and_dark_by_default(self):
        source = THEME_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("arena-ui-theme", source)
        self.assertIn("localStorage.getItem", source)
        self.assertIn("localStorage.setItem", source)
        self.assertIn("return 'dark'", source)
        self.assertIn("document.documentElement.dataset.theme", source)
        self.assertIn("window.addEventListener('storage'", source)

    def test_toggle_uses_reserved_account_slot(self):
        source = THEME_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("querySelector('.account-slot')", source)
        self.assertIn("accountSlot.prepend(button)", source)
        self.assertIn("data-theme-toggle", source)

    def test_both_stylesheets_define_light_palette_and_fixed_toggle(self):
        for path in THEME_STYLES:
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                self.assertIn(':root[data-theme="light"]', source)
                self.assertIn(".theme-toggle", source)
                self.assertIn("flex: 0 0 34px", source)


if __name__ == "__main__":
    unittest.main()
