import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MediaMtxPolicyTests(unittest.TestCase):
    def test_reference_configuration_supports_dual_ingress_safely(self):
        config = (
            PROJECT_ROOT / "mediamtx/mediamtx.yml.example"
        ).read_text(encoding="utf-8")

        self.assertIn("pass: CHANGE_ME_STRONG_MEDIA_PASSWORD", config)
        self.assertIn("path: '~^place([1-9]|1[0-6])$'", config)
        self.assertIn("rtmp: true", config)
        self.assertIn("rtmpAddress: :19350", config)
        self.assertIn("srt: true", config)
        self.assertIn("srtAddress: :8890", config)
        self.assertIn("hlsVariant: fmp4", config)
        self.assertIn("hlsSegmentCount: 15", config)
        self.assertIn("hlsAddress: 127.0.0.1:8888", config)
        self.assertIn("apiAddress: 127.0.0.1:9997", config)
        self.assertIn("metricsAddress: 127.0.0.1:9998", config)
        for place_id in range(1, 17):
            self.assertIn(f"  place{place_id}:", config)
        self.assertNotIn("83.219.", config)
        self.assertNotIn("138.124.", config)

    def test_service_is_hardened_and_uses_external_private_config(self):
        unit = (
            PROJECT_ROOT / "systemd/mediamtx.service"
        ).read_text(encoding="utf-8")

        self.assertIn("User=mediamtx", unit)
        self.assertIn(
            "ExecStart=/usr/local/bin/mediamtx "
            "/etc/mediamtx/mediamtx.yml",
            unit,
        )
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("ProtectHome=true", unit)
        self.assertIn(
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
            unit,
        )

    def test_general_updater_does_not_restart_mediamtx(self):
        updater = (
            PROJECT_ROOT / "scripts/update.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("mediamtx.service", updater)
        self.assertIn(
            "arena-mediamtx-ingress.service",
            updater,
        )
        services_block = updater.split(
            "readonly SERVICES=(",
            1,
        )[1].split(")", 1)[0]
        self.assertNotIn("mediamtx.service", services_block)
        self.assertIn(
            'for unit in "${SERVICES[@]}" "${OPTIONAL_UNITS[@]}"; do',
            updater,
        )
        self.assertNotIn("/etc/mediamtx/mediamtx.yml", updater)
        self.assertNotIn("/etc/mediamtx/ingress.yml", updater)


    def test_compatibility_ingress_unit_is_hardened(self):
        unit = (
            PROJECT_ROOT
            / "systemd/arena-mediamtx-ingress.service"
        ).read_text(encoding="utf-8")

        self.assertIn("User=mediamtx", unit)
        self.assertIn(
            "ExecStart=/usr/local/bin/mediamtx "
            "/etc/mediamtx/ingress.yml",
            unit,
        )
        self.assertIn(
            "Requires=mediamtx.service "
            "arena-rtmp-auth.service",
            unit,
        )
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("ProtectHome=true", unit)



if __name__ == "__main__":
    unittest.main()
