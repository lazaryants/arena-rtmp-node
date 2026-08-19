import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESTREAM_LOGROTATE = PROJECT_ROOT / "logrotate/arena-rtmp-node"


class LogrotatePolicyTests(unittest.TestCase):
    def test_restream_logs_are_rotated_without_reopening_ffmpeg_files(self):
        policy = RESTREAM_LOGROTATE.read_text(encoding="utf-8")

        self.assertIn(
            "/opt/arena-rtmp-node/logs/restream_field*.log",
            policy,
        )
        self.assertIn("su arena-rtmp arena-rtmp", policy)
        self.assertIn("daily", policy)
        self.assertIn("rotate 14", policy)
        self.assertIn("maxsize 10M", policy)
        self.assertIn("compress", policy)
        self.assertIn("copytruncate", policy)
        self.assertNotIn("audit.jsonl", policy)


if __name__ == "__main__":
    unittest.main()
