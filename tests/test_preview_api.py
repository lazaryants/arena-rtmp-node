import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import restream_manager
from app.settings import Settings


JPEG = b"\xff\xd8preview-frame\xff\xd9"


class PreviewApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        environment = {
            "ARENA_RTMP_ROOT": str(root),
            "ARENA_RTMP_PREVIEW_UPLOAD_TOKEN": "p" * 48,
            "ARENA_RTMP_RBAC_ENABLED": "true",
            "ARENA_RTMP_SESSION_SECRET": "s" * 48,
        }
        with patch.dict(os.environ, environment, clear=True):
            self.settings = Settings()
        self.settings.preview_dir.mkdir(parents=True)
        self.settings_patch = patch.object(
            restream_manager,
            "SETTINGS",
            self.settings,
        )
        self.settings_patch.start()
        restream_manager.app.config["TESTING"] = True
        self.client = restream_manager.app.test_client()

    def tearDown(self):
        self.settings_patch.stop()
        self.temporary_directory.cleanup()

    def upload(self, body=JPEG, token="p" * 48, content_type="image/jpeg"):
        return self.client.put(
            "/api/node/previews/7.jpg",
            data=body,
            content_type=content_type,
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_preview_upload_requires_dedicated_bearer_token(self):
        response = self.upload(token="wrong")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(
            (self.settings.preview_dir / "place7.jpg").exists()
        )

    def test_preview_is_atomically_stored_and_publicly_served(self):
        uploaded = self.upload()
        self.assertEqual(uploaded.status_code, 204)

        path = self.settings.preview_dir / "place7.jpg"
        self.assertEqual(path.read_bytes(), JPEG)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

        downloaded = self.client.get("/api/node/previews/7.jpg")
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.mimetype, "image/jpeg")
        self.assertEqual(downloaded.data, JPEG)
        self.assertIn("no-store", downloaded.headers["Cache-Control"])
        self.assertIn("X-Preview-Age", downloaded.headers)

    def test_preview_rejects_wrong_type_invalid_jpeg_and_large_body(self):
        self.assertEqual(
            self.upload(content_type="application/octet-stream").status_code,
            415,
        )
        self.assertEqual(self.upload(body=b"not-jpeg").status_code, 400)
        self.assertEqual(
            self.upload(body=b"\xff\xd8" + b"x" * (201 * 1024) + b"\xff\xd9")
            .status_code,
            413,
        )

    def test_preview_place_number_is_bounded(self):
        response = self.client.put(
            "/api/node/previews/17.jpg",
            data=JPEG,
            content_type="image/jpeg",
            headers={"Authorization": "Bearer " + "p" * 48},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
