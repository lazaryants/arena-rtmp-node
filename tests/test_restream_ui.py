import unittest
from pathlib import Path


class RestreamUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "templates"
            / "index.html"
        ).read_text(encoding="utf-8")

    def test_native_blocking_dialogs_and_page_reload_are_absent(self):
        for forbidden in (
            "prompt(",
            "alert(",
            "confirm(",
            "location.reload",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.template)

    def test_custom_dialog_and_toast_regions_exist(self):
        self.assertIn('id="dialogBackdrop"', self.template)
        self.assertIn('id="dialogForm"', self.template)
        self.assertIn('id="toastRegion"', self.template)
        self.assertIn("refreshFieldCard(fieldId)", self.template)

    def test_destination_audio_modes_are_available(self):
        self.assertIn('id="dialogAudioMode"', self.template)
        self.assertIn('value="source"', self.template)
        self.assertIn('value="silent"', self.template)
        self.assertIn('value="none"', self.template)
        self.assertIn("Source audio", self.template)
        self.assertIn("Silent AAC", self.template)
        self.assertIn("No audio track", self.template)
        self.assertIn("audio_mode: audioMode", self.template)

    def test_audio_mode_change_is_saved_immediately(self):
        self.assertIn(
            "onchange=\"saveAudioMode(",
            self.template,
        )
        self.assertIn(
            "async function saveAudioMode(fieldId, urlIndex)",
            self.template,
        )
        self.assertIn(
            "JSON.stringify({audio_mode: audioMode})",
            self.template,
        )
        self.assertIn(
            "Audio mode saved. Start the destination to apply it.",
            self.template,
        )

    def test_destination_url_validation_accepts_only_rtmp_schemes(self):
        self.assertIn("rtmps?:", self.template)
        self.assertIn(
            "The URL must start with rtmp:// or rtmps://.",
            self.template,
        )


if __name__ == "__main__":
    unittest.main()
