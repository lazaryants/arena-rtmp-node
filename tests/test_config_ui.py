import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigurationUiTests(unittest.TestCase):
    def source(self):
        return (PROJECT_ROOT / "app/templates/config.html").read_text(
            encoding="utf-8",
        )

    def test_complete_camera_url_and_copy_control_are_rendered(self):
        source = self.source()
        self.assertIn("Full camera URL", source)
        self.assertIn("field.publish_url", source)
        self.assertIn("copyPublishUrl", source)

    def test_key_rotation_uses_custom_confirmation_and_server_endpoint(self):
        source = self.source()
        self.assertIn('id="rotateKeyModal"', source)
        self.assertIn("confirmKeyRotation", source)
        self.assertIn("/rotate-key", source)
        self.assertNotIn("generateRandomKey", source)
        self.assertNotIn("regenerateKey", source)
        self.assertNotIn(
            "Generate a new random key for this field?",
            source,
        )


if __name__ == "__main__":
    unittest.main()
