import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MonitoringNavigationTests(unittest.TestCase):
    def test_privileged_links_are_hidden_until_role_is_loaded(self):
        html = (PROJECT_ROOT / "web/index.html").read_text(
            encoding="utf-8",
        )
        self.assertIn('id="signInNavLink"', html)
        self.assertIn('href="/admin/login?next=/"', html)
        self.assertIn('id="configurationNavLink"', html)
        self.assertIn('data-minimum-role="admin"', html)
        self.assertIn('id="restreamNavLink"', html)
        self.assertIn('data-minimum-role="operator"', html)
        self.assertGreaterEqual(html.count("hidden>"), 2)

    def test_monitoring_details_can_be_hidden_and_preference_is_saved(self):
        html = (PROJECT_ROOT / "web/index.html").read_text(
            encoding="utf-8",
        )
        script = (PROJECT_ROOT / "web/script.js").read_text(
            encoding="utf-8",
        )
        styles = (PROJECT_ROOT / "web/style.css").read_text(
            encoding="utf-8",
        )

        self.assertIn('id="detailsToggle"', html)
        self.assertIn('aria-pressed="false"', html)
        self.assertIn("MONITOR_DETAILS_KEY", script)
        self.assertIn("setupMonitorDetails();", script)
        self.assertIn("localStorage.setItem(MONITOR_DETAILS_KEY", script)
        self.assertIn("details-hidden", script)
        self.assertIn(".grid.details-hidden .stream-details", styles)

    def test_mobile_players_only_run_inside_the_viewport(self):
        html = (PROJECT_ROOT / "web/index.html").read_text(
            encoding="utf-8",
        )
        script = (PROJECT_ROOT / "web/script.js").read_text(
            encoding="utf-8",
        )

        self.assertIn("script.js?v=9", html)
        self.assertIn("<h1>Live cameras Arena76</h1>", html)
        self.assertNotIn("Field monitoring", html)
        self.assertNotIn("India &amp; Pakistan", html)
        self.assertIn("MOBILE_PLAYBACK_QUERY", script)
        self.assertIn("CONSERVE_MOBILE_PLAYBACK", script)
        self.assertIn("MOBILE_MAX_ACTIVE_PLAYERS = 2", script)
        self.assertIn("rebalanceMobilePlayback()", script)
        self.assertIn(".slice(0, MOBILE_MAX_ACTIVE_PLAYERS)", script)
        self.assertIn("new IntersectionObserver", script)
        self.assertIn("state.ratio >= 0.25", script)
        self.assertIn("entry.intersectionRatio", script)
        self.assertIn("setPlaybackAllowed", script)
        self.assertIn("viewportObserver.disconnect()", script)
        self.assertIn("releaseMedia()", script)

    def test_navigation_uses_safe_session_metadata(self):
        script = (PROJECT_ROOT / "web/script.js").read_text(
            encoding="utf-8",
        )
        self.assertIn("async function refreshNavigationAccess()", script)
        self.assertIn("fetch('/api/session'", script)
        self.assertIn("getElementById('signInNavLink')", script)
        self.assertIn(
            "signInLink.hidden = legacyMode || payload.authenticated",
            script,
        )
        self.assertIn("operator: 1", script)
        self.assertIn("manager: 2", script)
        self.assertIn("admin: 3", script)
        self.assertIn("refreshNavigationAccess();", script)


if __name__ == "__main__":
    unittest.main()
