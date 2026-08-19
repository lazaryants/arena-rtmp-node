import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
THEME_SCRIPT = PROJECT_ROOT / "web/theme.js"
SAND_TEXTURE = PROJECT_ROOT / "web/sand-texture.svg"
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
                self.assertIn("theme.js?v=2", source)
                self.assertLess(
                    source.index("theme.js?v=2"),
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

    def test_existing_light_preference_is_migrated_to_ice(self):
        source = THEME_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("value === 'light'", source)
        self.assertIn("return 'ice'", source)

    def test_picker_uses_reserved_account_slot(self):
        source = THEME_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("querySelector('.account-slot')", source)
        self.assertIn("accountSlot.prepend(wrapper)", source)
        self.assertIn("data-theme-picker", source)
        self.assertIn("data-theme-option", source)
        self.assertIn("Dark", source)
        self.assertIn("Ice", source)
        self.assertIn("Sand", source)

    def test_stylesheets_define_ice_sand_and_fixed_picker(self):
        for path in THEME_STYLES:
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                self.assertIn(':root[data-theme="ice"]', source)
                self.assertIn(':root[data-theme="sand"]', source)
                self.assertIn(".theme-picker", source)
                self.assertIn(".theme-menu", source)
                self.assertIn("flex: 0 0 34px", source)
                self.assertIn('url("/sand-texture.svg?v=3")', source)
                self.assertIn("320px 240px", source)
                self.assertIn('calc(32% - 1px)', source)
                self.assertIn('calc(50% - 1px)', source)
                self.assertIn('calc(68% - 1px)', source)
                self.assertIn(':root[data-theme="ice"] .topbar', source)

    def test_light_themes_define_readable_code_and_disabled_text(self):
        expected = (
            "--code-text: #0a568d;",
            "--code-text: #70480f;",
            "--disabled-card-opacity: 0.76;",
            "color: var(--code-text);",
            "opacity: var(--disabled-card-opacity);",
        )
        for path in THEME_STYLES:
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                for declaration in expected:
                    self.assertIn(declaration, source)

    def test_sand_texture_has_visible_irregular_grains(self):
        source = SAND_TEXTURE.read_text(encoding="utf-8")

        self.assertGreaterEqual(source.count("<ellipse"), 300)
        self.assertNotIn("<path", source)
        self.assertIn('fill="#6f604d"', source)
        self.assertIn('fill="#fffdf7"', source)



if __name__ == "__main__":
    unittest.main()
