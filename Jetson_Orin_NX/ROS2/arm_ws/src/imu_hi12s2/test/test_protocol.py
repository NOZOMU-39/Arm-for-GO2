# -*- coding: utf-8 -*-
"""imu_hi12s2 协议层单元测试（纯逻辑，不需要硬件）。

跑法：cd src/imu_hi12s2 && python3 -m unittest discover -s test -t . -v
"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from imu_hi12s2.protocol import (  # noqa: E402
    HEAD,
    PAYLOAD_091_LEN,
    FrameSplitter,
    build_frame_091,
    crc16_xmodem,
    parse_091,
)


class TestCrc(unittest.TestCase):
    def test_selftest_vector(self):
        self.assertEqual(crc16_xmodem(b"123456789"), 0x31C3)


class TestFrame(unittest.TestCase):
    def setUp(self):
        self.splitter = FrameSplitter()

    def test_build_and_parse_roundtrip(self):
        frame = build_frame_091({
            "main_status": 0x1A00, "temperature": -3, "system_time": 12345,
            "ax": 0.1, "ay": 0.2, "az": 1.0, "gx": 1.5, "gy": -2.5, "gz": 0.0,
            "roll": 1.0, "pitch": 2.0, "yaw": 3.0,
            "qw": 0.9, "qx": 0.1, "qy": 0.2, "qz": 0.3,
        })
        frames = self.splitter.feed(frame)
        self.assertEqual(len(frames), 1)
        field = parse_091(frames[0])
        self.assertEqual(field["tag"], 0x91)
        self.assertEqual(field["main_status"], 0x1A00)
        self.assertEqual(field["temperature"], -3)
        self.assertEqual(field["system_time"], 12345)
        self.assertAlmostEqual(field["gz"], 0.0)
        self.assertAlmostEqual(field["qw"], 0.9)

    def test_frame_length_is_82(self):
        frame = build_frame_091({})
        self.assertEqual(len(frame), 82)
        self.assertEqual(PAYLOAD_091_LEN, 76)
        self.assertEqual(frame[:2], HEAD)

    def test_garbage_prefix_is_resynced(self):
        frame = build_frame_091({"system_time": 7})
        frames = self.splitter.feed(b"\x00\x11\x22" + frame)
        self.assertEqual(len(frames), 1)
        self.assertEqual(parse_091(frames[0])["system_time"], 7)
        self.assertGreater(self.splitter.resync_bytes, 0)

    def test_corrupt_payload_counts_crc_bad(self):
        frame = bytearray(build_frame_091({"system_time": 1}))
        frame[20] ^= 0xFF
        frames = self.splitter.feed(bytes(frame))
        self.assertEqual(frames, [])
        self.assertEqual(self.splitter.crc_bad, 1)

    def test_split_across_reads(self):
        frame = build_frame_091({"system_time": 99})
        self.assertEqual(self.splitter.feed(frame[:17]), [])
        frames = self.splitter.feed(frame[17:])
        self.assertEqual(len(frames), 1)
        self.assertEqual(parse_091(frames[0])["system_time"], 99)

    def test_two_frames_in_one_read(self):
        a = build_frame_091({"system_time": 1})
        b = build_frame_091({"system_time": 2})
        frames = self.splitter.feed(a + b)
        self.assertEqual([parse_091(f)["system_time"] for f in frames], [1, 2])

    def test_valid_crc_other_length_is_len_bad(self):
        payload = b"\x81" + b"\x00" * 9          # 长度 10，CRC 合法但非 0x91 全量帧
        head = HEAD + struct.pack("<H", len(payload))
        frame = head + struct.pack("<H", crc16_xmodem(head + payload)) + payload
        frames = self.splitter.feed(frame)
        self.assertEqual(frames, [])
        self.assertEqual(self.splitter.len_bad, 1)

    def test_false_head_inside_payload_does_not_eat_frame(self):
        # 造一个 payload 里含 5A A5 的帧，确认重同步不会误吃后面的真帧
        tricky = build_frame_091({"system_time": 3})
        good = build_frame_091({"system_time": 4})
        frames = self.splitter.feed(tricky + b"\x5a\xa5" + good)
        times = [parse_091(f)["system_time"] for f in frames]
        self.assertIn(3, times)
        self.assertIn(4, times)


if __name__ == "__main__":
    unittest.main()
