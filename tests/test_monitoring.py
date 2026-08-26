import json
import os
import tempfile
import time
import unittest
from dataclasses import replace
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from app.monitoring import (
    health_snapshot,
    merge_mediamtx_snapshot,
    merge_rtmp_snapshot,
    metrics_snapshot,
    parse_mediamtx_paths,
    parse_rtmp_stat,
)
from app.settings import Settings


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.hls_root = self.root / "hls"
        self.hls_root.mkdir()
        self.ffmpeg = self.root / "ffmpeg"
        self.ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")
        self.ffmpeg.chmod(0o755)

        environment = {
            "ARENA_RTMP_ROOT": str(self.root),
            "ARENA_RTMP_HLS_ROOT": str(self.hls_root),
            "ARENA_RTMP_FFMPEG": str(self.ffmpeg),
            "ARENA_RTMP_STAT_URL": "http://127.0.0.1:8090/stat",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.settings = Settings()

        self.settings.config_file.parent.mkdir(parents=True)
        self.settings.config_file.write_text(
            json.dumps({
                "schema_version": 2,
                "fields": {
                    "1": {
                        "enabled": True,
                        "stream_key": "stream1",
                        "key": "publish-secret",
                        "publish_auth_enabled": True,
                        "restream_urls": [{
                            "url": "rtmp://destination.example/live/private-token",
                            "audio_mode": "source",
                        }],
                    },
                },
            }),
            encoding="utf-8",
        )

        place1 = self.hls_root / "place1"
        place1.mkdir()
        segment = place1 / "stream1-1.ts"
        segment.write_bytes(b"segment")
        os.utime(segment, (time.time(), time.time()))

    def tearDown(self):
        self.temporary_directory.cleanup()

    @patch("app.monitoring.rtmp_snapshot")
    def test_metrics_are_safe_and_report_active_hls(self, mocked_rtmp):
        mocked_rtmp.return_value = {
            "reachable": True,
            "active_streams": 1,
            "clients": 1,
            "applications": {"place1": {"streams": 1, "clients": 1}},
        }
        metrics = metrics_snapshot(self.settings)
        serialized = json.dumps(metrics)

        self.assertEqual(metrics["hls"]["places"]["1"]["state"], "active")
        self.assertEqual(metrics["config"]["schema_version"], 2)
        self.assertEqual(metrics["config"]["publish_auth_enabled_places"], 1)
        self.assertNotIn("publish-secret", serialized)
        self.assertNotIn("private-token", serialized)
        self.assertNotIn("restream_urls", serialized)

    @patch("app.monitoring.rtmp_snapshot")
    def test_health_is_ok_when_dependencies_are_ready(self, mocked_rtmp):
        mocked_rtmp.return_value = {"reachable": True}
        health = health_snapshot(self.settings)
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["checks"]["config"]["schema_version"], 2)
        self.assertTrue(all(check["ok"] for check in health["checks"].values()))

    @patch("app.monitoring.mediamtx_snapshot")
    @patch("app.monitoring.rtmp_snapshot")
    def test_full_mediamtx_health_does_not_require_nginx_stat(
        self,
        mocked_rtmp,
        mocked_mediamtx,
    ):
        settings = replace(
            self.settings,
            mediamtx_hls_places=tuple(
                range(1, 17)
            ),
        )
        mocked_mediamtx.return_value = {
            "reachable": True,
        }

        health = health_snapshot(settings)

        self.assertEqual(health["status"], "ok")
        self.assertTrue(
            health["checks"]["mediamtx_api"]["ok"]
        )
        self.assertNotIn(
            "rtmp_stat",
            health["checks"],
        )
        mocked_rtmp.assert_not_called()

    @patch("app.monitoring.mediamtx_snapshot")
    @patch("app.monitoring.rtmp_snapshot")
    def test_partial_mediamtx_health_still_requires_nginx_stat(
        self,
        mocked_rtmp,
        mocked_mediamtx,
    ):
        settings = replace(
            self.settings,
            mediamtx_hls_places=(1, 2, 3),
        )
        mocked_mediamtx.return_value = {
            "reachable": True,
        }
        mocked_rtmp.side_effect = OSError(
            "nginx stat unavailable"
        )

        health = health_snapshot(settings)

        self.assertEqual(
            health["status"],
            "degraded",
        )
        self.assertFalse(
            health["checks"]["rtmp_stat"]["ok"]
        )
        self.assertTrue(
            health["checks"]["mediamtx_api"]["ok"]
        )
        mocked_rtmp.assert_called_once()

    def test_rtmp_metrics_are_server_side_and_do_not_expose_identity(self):
        root = ET.fromstring("""
            <rtmp>
              <server>
                <application>
                  <name>place16</name>
                  <live>
                    <stream>
                      <name>private-stream-key</name>
                      <time>9574060</time>
                      <bw_in>1567672</bw_in>
                      <bytes_in>1235480564</bytes_in>
                      <bw_audio>192712</bw_audio>
                      <bw_video>1374952</bw_video>
                      <client>
                        <address>203.0.113.10</address>
                        <publishing/>
                        <dropped>3</dropped>
                      </client>
                      <client>
                        <address>127.0.0.1</address>
                        <dropped>99</dropped>
                      </client>
                      <nclients>2</nclients>
                      <meta>
                        <video>
                          <width>1920</width>
                          <height>1080</height>
                          <frame_rate>30</frame_rate>
                          <codec>H264</codec>
                          <profile>High</profile>
                          <level>4.0</level>
                        </video>
                        <audio>
                          <codec>AAC</codec>
                          <profile>LC</profile>
                          <channels>2</channels>
                          <sample_rate>44100</sample_rate>
                        </audio>
                      </meta>
                    </stream>
                  </live>
                </application>
              </server>
            </rtmp>
        """)

        snapshot = parse_rtmp_stat(root)
        stream = snapshot["applications"]["place16"]["stream_metrics"][0]
        serialized = json.dumps(snapshot)

        self.assertEqual(snapshot["active_streams"], 1)
        self.assertEqual(snapshot["clients"], 2)
        self.assertEqual(stream["uptime_seconds"], 9574.1)
        self.assertEqual(stream["input_bitrate_bps"], 1567672)
        self.assertEqual(stream["video_bitrate_bps"], 1374952)
        self.assertEqual(stream["audio_bitrate_bps"], 192712)
        self.assertEqual(stream["publishers"], 1)
        self.assertEqual(stream["players"], 1)
        self.assertEqual(stream["publisher_dropped"], 3)
        self.assertEqual(stream["video"]["resolution"], "1920x1080")
        self.assertEqual(stream["video"]["source_fps"], 30.0)
        self.assertEqual(stream["audio"]["sample_rate_hz"], 44100)
        self.assertNotIn("private-stream-key", serialized)
        self.assertNotIn("203.0.113.10", serialized)

    def test_rtmp_metrics_tolerate_missing_metadata(self):
        root = ET.fromstring("""
            <rtmp>
              <server>
                <application>
                  <name>place2</name>
                  <live>
                    <stream>
                      <nclients>0</nclients>
                    </stream>
                  </live>
                </application>
              </server>
            </rtmp>
        """)

        stream = parse_rtmp_stat(root)[
            "applications"
        ]["place2"]["stream_metrics"][0]

        self.assertIsNone(stream["uptime_seconds"])
        self.assertIsNone(stream["input_bitrate_bps"])
        self.assertIsNone(stream["video"]["resolution"])
        self.assertIsNone(stream["audio"]["codec"])
        self.assertEqual(stream["publisher_dropped"], 0)

    def test_worker_local_snapshots_are_merged_until_hls_has_no_signal(self):
        cache = {}
        active_hls = {
            "places": {
                "8": {"state": "active"},
                "16": {"state": "active"},
            },
        }
        worker_one = {
            "reachable": True,
            "active_streams": 1,
            "clients": 1,
            "applications": {
                "place8": {
                    "streams": 1,
                    "clients": 1,
                    "stream_metrics": [{"publishers": 1}],
                },
            },
        }
        worker_two = {
            "reachable": True,
            "active_streams": 1,
            "clients": 2,
            "applications": {
                "place16": {
                    "streams": 1,
                    "clients": 2,
                    "stream_metrics": [{"publishers": 1}],
                },
            },
        }

        first = merge_rtmp_snapshot(worker_one, active_hls, cache)
        second = merge_rtmp_snapshot(worker_two, active_hls, cache)

        self.assertEqual(set(first["applications"]), {"place8"})
        self.assertEqual(
            set(second["applications"]),
            {"place8", "place16"},
        )
        self.assertEqual(second["active_streams"], 2)
        self.assertEqual(second["clients"], 3)

        no_signal_hls = {
            "places": {
                "8": {"state": "no_signal"},
                "16": {"state": "active"},
            },
        }
        third = merge_rtmp_snapshot(
            {"reachable": True, "applications": {}},
            no_signal_hls,
            cache,
        )
        self.assertEqual(set(third["applications"]), {"place16"})


    def test_mediamtx_paths_use_existing_safe_source_schema(self):
        rate_cache = {}
        first = parse_mediamtx_paths(
            {
                "items": [{
                    "name": "place9",
                    "ready": True,
                    "onlineTime": "2026-08-23T06:43:25Z",
                    "source": {"type": "srtConn", "id": "private-id"},
                    "tracks2": [
                        {
                            "codec": "H264",
                            "codecProps": {
                                "width": 1920,
                                "height": 1080,
                                "profile": "High",
                                "level": "4",
                            },
                        },
                        {
                            "codec": "MPEG-4 Audio",
                            "codecProps": {
                                "sampleRate": 48000,
                                "channelCount": 1,
                            },
                        },
                    ],
                    "readers": [],
                    "inboundBytes": 1000,
                    "inboundFramesInError": 0,
                }],
            },
            (9, 10),
            now=1787467410.0,
            rate_cache=rate_cache,
        )
        second = parse_mediamtx_paths(
            {
                "items": [{
                    "name": "place9",
                    "ready": True,
                    "onlineTime": "2026-08-23T06:43:25Z",
                    "source": {"type": "srtConn", "id": "private-id"},
                    "tracks2": [
                        {
                            "codec": "H264",
                            "codecProps": {
                                "width": 1920,
                                "height": 1080,
                                "profile": "High",
                                "level": "4",
                            },
                        },
                        {
                            "codec": "MPEG-4 Audio",
                            "codecProps": {
                                "sampleRate": 48000,
                                "channelCount": 1,
                            },
                        },
                    ],
                    "readers": [],
                    "inboundBytes": 2000,
                    "inboundFramesInError": 0,
                }],
            },
            (9, 10),
            now=1787467412.0,
            rate_cache=rate_cache,
        )

        stream = second["applications"]["place9"]["stream_metrics"][0]
        serialized = json.dumps(second)
        self.assertEqual(first["active_streams"], 1)
        self.assertEqual(stream["input_bitrate_bps"], 4000)
        self.assertEqual(stream["video"]["resolution"], "1920x1080")
        self.assertEqual(stream["video"]["profile"], "High")
        self.assertEqual(stream["audio"]["codec"], "AAC")
        self.assertEqual(stream["audio"]["sample_rate_hz"], 48000)
        self.assertEqual(stream["publishers"], 1)
        self.assertEqual(stream["publisher_dropped"], 0)
        self.assertNotIn("private-id", serialized)
        self.assertNotIn("srtConn", serialized)

    def test_mediamtx_place_overrides_hls_and_keeps_rtmp_places(self):
        hls = {
            "counts": {"active": 1, "stale": 0, "no_signal": 15},
            "places": {
                str(place_id): {
                    "state": "active" if place_id == 1 else "no_signal",
                    "latest_segment_age_seconds": (
                        1.0 if place_id == 1 else None
                    ),
                }
                for place_id in range(1, 17)
            },
        }
        rtmp = {
            "reachable": False,
            "applications": {
                "place1": {
                    "streams": 1,
                    "clients": 1,
                    "stream_metrics": [{"publishers": 1}],
                },
            },
        }
        mediamtx = {
            "reachable": True,
            "applications": {
                "place9": {
                    "streams": 1,
                    "clients": 1,
                    "stream_metrics": [{"publishers": 1}],
                },
            },
        }

        merged = merge_mediamtx_snapshot(
            rtmp,
            hls,
            mediamtx,
            (9, 10),
        )

        self.assertEqual(
            set(merged["applications"]),
            {"place1", "place9"},
        )
        self.assertEqual(merged["active_streams"], 2)
        self.assertTrue(merged["reachable"])
        self.assertEqual(hls["places"]["9"]["state"], "active")
        self.assertEqual(hls["places"]["10"]["state"], "no_signal")
        self.assertEqual(hls["counts"]["active"], 2)


if __name__ == "__main__":
    unittest.main()
