import json
import tempfile
import unittest
from pathlib import Path

from scripts.render_nginx import render


class RenderNginxTests(unittest.TestCase):
    def profile(self):
        return {
            "server_names": ["rtmp.example.test", "node.example.test"],
            "tls_certificate": "/etc/tls/fullchain.pem",
            "tls_certificate_key": "/etc/tls/privkey.pem",
            "web_root": "/opt/arena-rtmp-node/web",
            "hls_root": "/var/www/hls",
            "basic_auth_file": "/etc/nginx/.htpasswd",
            "manager_upstream": "127.0.0.1:5000",
            "mediamtx_hls_upstream": "127.0.0.1:8888",
            "mediamtx_hls_places": [9, 10],
            "rtmp_port": 1935,
            "auth_callback": "http://127.0.0.1:8080/auth",
            "auth_places": [15],
        }

    def render_profile(self, profile):
        temporary_directory = tempfile.TemporaryDirectory()
        root = Path(temporary_directory.name)
        profile_path = root / "profile.json"
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        outputs = render(profile_path, root / "output")
        return temporary_directory, outputs

    def test_renders_all_places_and_selected_auth(self):
        temporary_directory, outputs = self.render_profile(self.profile())
        self.addCleanup(temporary_directory.cleanup)

        rtmp = outputs["arena-rtmp.conf"]
        http = outputs["arena-rtmp-http.conf"]
        self.assertEqual(rtmp.count("application place"), 16)
        self.assertEqual(rtmp.count("on_publish "), 1)
        self.assertEqual(rtmp.count("rtmp_auto_push on;"), 1)
        self.assertEqual(rtmp.count("rtmp_auto_push_reconnect 1s;"), 1)
        self.assertLess(rtmp.index("rtmp_auto_push on;"), rtmp.index("rtmp {"))
        self.assertIn("application place15", rtmp)
        self.assertIn("rtmp.example.test node.example.test", http)
        self.assertIn("location ^~ /.well-known/acme-challenge/", http)
        self.assertIn("root /var/lib/letsencrypt;", http)
        self.assertIn("auth_basic off;", http)
        self.assertIn("return 301 https://$host$request_uri;", http)
        self.assertIn("location ^~ /hls/place9/", http)
        self.assertIn("location ^~ /hls/place10/", http)
        self.assertIn(
            "rewrite ^/hls/place9/stream9\\.m3u8$ "
            "/place9/index.m3u8 break;",
            http,
        )
        self.assertIn("proxy_pass http://127.0.0.1:8888;", http)
        self.assertIn(
            "proxy_cookie_path /place9/ /hls/place9/;",
            http,
        )
        self.assertLess(
            http.index("location ^~ /hls/place9/"),
            http.index("location ~ ^/hls/place"),
        )
        self.assertNotIn("@@", rtmp + http)

    def test_application_rbac_replaces_nginx_basic_auth(self):
        temporary_directory, outputs = self.render_profile(self.profile())
        self.addCleanup(temporary_directory.cleanup)

        http = outputs["arena-rtmp-http.conf"]
        self.assertNotIn('auth_basic "Restricted Access";', http)
        self.assertNotIn("auth_basic_user_file", http)
        self.assertIn(
            "location = /api/fields {\n"
            "        proxy_pass ",
            http,
        )
        self.assertIn(
            "location = /api/session {\n"
            "        proxy_pass ",
            http,
        )
        self.assertIn(
            "location /api/node/ {\n"
            "        proxy_pass ",
            http,
        )
        self.assertIn(
            "location / {\n"
            "        try_files $uri $uri/ =404;",
            http,
        )

    def test_omits_mediamtx_locations_by_default(self):
        profile = self.profile()
        profile.pop("mediamtx_hls_upstream")
        profile.pop("mediamtx_hls_places")
        temporary_directory, outputs = self.render_profile(profile)
        self.addCleanup(temporary_directory.cleanup)

        http = outputs["arena-rtmp-http.conf"]
        self.assertNotIn("location ^~ /hls/place9/", http)
        self.assertNotIn("proxy_pass http://127.0.0.1:8888;", http)

    def test_requires_local_mediamtx_upstream(self):
        profile = self.profile()
        profile["mediamtx_hls_upstream"] = "media.example.test:8888"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "127.0.0.1"):
                render(profile_path, root / "output")

    def test_requires_upstream_for_mediamtx_places(self):
        profile = self.profile()
        profile.pop("mediamtx_hls_upstream")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "required"):
                render(profile_path, root / "output")

    def test_rejects_unsafe_path(self):
        profile = self.profile()
        profile["web_root"] = "/var/www; include /tmp/evil"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsafe characters"):
                render(profile_path, root / "output")

    def test_rejects_non_local_callback(self):
        profile = self.profile()
        profile["auth_callback"] = "https://example.test/auth"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "local"):
                render(profile_path, root / "output")


if __name__ == "__main__":
    unittest.main()
