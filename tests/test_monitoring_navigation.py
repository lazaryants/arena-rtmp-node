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

    def test_mobile_uses_jpeg_until_one_player_is_requested(self):
        html = (PROJECT_ROOT / "web/index.html").read_text(
            encoding="utf-8",
        )
        script = (PROJECT_ROOT / "web/script.js").read_text(
            encoding="utf-8",
        )
        styles = (PROJECT_ROOT / "web/style.css").read_text(
            encoding="utf-8",
        )

        self.assertIn("script.js?v=15", html)
        self.assertIn("style.css?v=16", html)
        self.assertIn("<h1>Live cameras Arena76</h1>", html)
        self.assertIn("MOBILE_PLAYBACK_QUERY", script)
        self.assertIn("MOBILE_PREVIEW_REFRESH_MS = 2000", script)
        self.assertIn("mobilePlayerControls", script)
        self.assertIn("selectMobilePlayer(playerId)", script)
        self.assertIn("selectMobilePlayer(null)", script)
        self.assertIn(
            "/api/node/previews/${stream.prefix}.jpg",
            script,
        )
        self.assertIn("mobile-preview-image", script)
        self.assertIn("mobile-live-toggle", script)
        self.assertIn("allowed ? '■' : '▶'", script)
        self.assertIn("toggle.setAttribute('aria-label', label)", script)
        self.assertNotIn("MOBILE_MAX_ACTIVE_PLAYERS", script)
        self.assertNotIn("MOBILE_ROTATION_INTERVAL_MS", script)
        self.assertNotIn("new IntersectionObserver", script)
        self.assertNotIn("capturePreviewFrame()", script)
        self.assertIn(".mobile-preview-image", styles)
        self.assertIn(".mobile-live-active", styles)
        self.assertIn("display: none", styles)
        self.assertIn("playsinline", script)

    def test_mobile_and_desktop_layout_preferences_are_independent(self):
        html = (PROJECT_ROOT / "web/index.html").read_text(
            encoding="utf-8",
        )
        script = (PROJECT_ROOT / "web/script.js").read_text(
            encoding="utf-8",
        )
        styles = (PROJECT_ROOT / "web/style.css").read_text(
            encoding="utf-8",
        )

        self.assertIn('data-columns="1"', html)
        self.assertIn('class="mobile-column-option"', html)
        self.assertEqual(html.count('class="desktop-column-option"'), 2)
        self.assertIn("MONITOR_MOBILE_LAYOUT_KEY", script)
        self.assertIn("? ['1', '2']", script)
        self.assertIn(": ['2', '3', '4']", script)
        self.assertIn("'columns-1'", script)
        self.assertIn(".grid.columns-1", styles)
        self.assertIn(".layout-switcher .mobile-column-option", styles)
        self.assertIn(".layout-switcher .desktop-column-option", styles)


    def test_hls_metadata_fills_fps_and_segment_metrics(self):
        script = (PROJECT_ROOT / "web/script.js").read_text(
            encoding="utf-8",
        )

        self.assertIn("function getHlsFrameRate(hls)", script)
        self.assertIn("level?.frameRate", script)
        self.assertIn("function getSegmentColorClass(value)", script)
        self.assertIn("value >= 1.5 && value <= 6", script)
        self.assertNotIn("4.0s <span", script)
        self.assertIn(">Ingest errors</span>", script)
        self.assertIn(">Signal age</span>", script)
        self.assertIn(
            "Duration of one HLS media fragment; "
            "this is not stream latency",
            script,
        )

    def test_desktop_hls_buffers_are_bounded_for_chromium(self):
        script = (PROJECT_ROOT / "web/script.js").read_text(
            encoding="utf-8",
        )

        self.assertIn("liveMaxLatencyDurationCount: 6", script)
        self.assertIn("maxBufferLength: 12", script)
        self.assertIn("maxMaxBufferLength: 20", script)
        self.assertIn("backBufferLength: 8", script)
        self.assertNotIn("liveMaxLatencyDurationCount: 10", script)


    def test_chrome_startup_stall_does_not_rebuild_players(self):
        script = (PROJECT_ROOT / "web/script.js").read_text(
            encoding="utf-8",
        )

        self.assertIn("PLAYER_STALL_TIMEOUT_MS = 15000", script)
        self.assertIn(
            "active stream is not advancing",
            script,
        )
        self.assertNotIn(
            "scheduleRecovery('video stalled')",
            script,
        )
        self.assertNotIn(
            "scheduleRecovery('stream became active')",
            script,
        )
        self.assertIn(
            "&& hls === null",
            script,
        )


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
