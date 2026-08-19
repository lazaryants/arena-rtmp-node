import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
THEME_SCRIPT = PROJECT_ROOT / "web/theme.js"
SAND_TEXTURE = PROJECT_ROOT / "web/sand-texture.svg"
SAND_BACKGROUND = PROJECT_ROOT / "web/sand-waves-v2.webp"
ICE_BACKGROUND = PROJECT_ROOT / "web/curling-two-sheets.webp"
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
                self.assertIn('url("/sand-waves-v2.webp?v=2")', source)
                self.assertIn("max(100vw, 1200px) auto", source)
                self.assertIn(':root[data-theme="sand"] .brand-title', source)
                self.assertIn(':root[data-theme="sand"] .account-action', source)
                self.assertIn(':root[data-theme="sand"] .topbar::before', source)
                self.assertIn("width: 100vw", source)
                self.assertIn('url("/curling-two-sheets.webp?v=1")', source)
                self.assertIn("background-attachment: fixed", source)
                self.assertIn(':root[data-theme="ice"] .topbar::before', source)
                self.assertIn(':root[data-theme="ice"] .stream-card', source)
                self.assertIn(':root[data-theme="ice"] .user-panel', source)
                self.assertIn("background-size: auto 920px", source)

    def test_light_themes_define_readable_code_and_disabled_text(self):
        expected = (
            "--code-text: #0a568d;",
            "--code-text: #70480f;",
            "color: var(--code-text);",
        )
        for path in THEME_STYLES:
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                for declaration in expected:
                    self.assertIn(declaration, source)

        admin_source = THEME_STYLES[1].read_text(encoding="utf-8")
        self.assertIn("margin: 0;", admin_source)
        self.assertIn("--disabled-card-opacity: 0.76;", admin_source)
        self.assertIn("opacity: var(--disabled-card-opacity);", admin_source)

    def test_sand_texture_has_visible_irregular_grains(self):
        source = SAND_TEXTURE.read_text(encoding="utf-8")

        self.assertGreaterEqual(source.count("<ellipse"), 300)
        self.assertNotIn("<path", source)
        self.assertIn('fill="#6f604d"', source)
        self.assertIn('fill="#fffdf7"', source)

    def test_sand_v2_background_is_local_optimized_webp(self):
        source = SAND_BACKGROUND.read_bytes()

        self.assertEqual(source[:4], b"RIFF")
        self.assertEqual(source[8:12], b"WEBP")
        self.assertGreater(len(source), 20_000)
        self.assertLess(len(source), 200_000)

    def test_ice_background_is_local_optimized_webp(self):
        source = ICE_BACKGROUND.read_bytes()

        self.assertEqual(source[:4], b"RIFF")
        self.assertEqual(source[8:12], b"WEBP")
        self.assertGreater(len(source), 50_000)
        self.assertLess(len(source), 200_000)



if __name__ == "__main__":
    unittest.main()
