# -*- coding: utf-8 -*-
"""M2 单测：定长记录、环形缓冲、配额、导出。

不碰硬件、不依赖 ROS，Windows/Linux 都能跑：
    python -m unittest discover -s test -t .
"""
import json
import os
import shutil
import tempfile
import time
import unittest

from imu_core import exporter, quota, record
from imu_core.ring import MultiRing, Ring
from imu_core.types import ImuSample


def make_sample(i=0, role="muzzle", t0=1_700_000_000_000_000_000):
    return ImuSample(
        t_rx_ns=t0 + i * 1_000_000, device="uuid:TEST", role=role,
        t_sys_ms=1000 + i, ax=0.1 * i, ay=-0.2, az=1.0,
        gx=0.01 * i, gy=0.02, gz=-0.03,
        roll=1.0, pitch=2.0, yaw=3.0,
        qw=0.9, qx=0.1, qy=0.2, qz=0.3,
        temperature=34 + (i % 3) - 1, status=0x1a00, seq=i,
    )


def make_meta(path, created, state="closed", frames=10, keep=False):
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, record.META_NAME), "w", encoding="utf-8") as fh:
        json.dump({"schema": record.SCHEMA, "created_epoch": created, "state": state,
                   "streams": {"muzzle": {"file": "muzzle.bin", "frames": frames}}}, fh)
    with open(os.path.join(path, "muzzle.bin"), "wb") as fh:
        fh.write(b"\0" * record.RECORD_SIZE)
    if keep:
        open(os.path.join(path, record.KEEP_NAME), "a").close()


class TestRecord(unittest.TestCase):
    def test_record_is_64_bytes(self):
        self.assertEqual(record.RECORD_SIZE, 64)
        self.assertEqual(record.RECORD.size, 64)

    def test_pack_unpack_roundtrip(self):
        s = make_sample(7)
        rec = record.unpack(record.pack(s))
        self.assertEqual(rec["t_rx_ns"], s.t_rx_ns)
        self.assertEqual(rec["seq"], 7)
        self.assertEqual(rec["t_sys_ms"], s.t_sys_ms)
        self.assertAlmostEqual(rec["ax"], s.ax, places=5)
        self.assertAlmostEqual(rec["gz"], s.gz, places=5)
        self.assertAlmostEqual(rec["qw"], s.qw, places=3)
        self.assertEqual(rec["status"], 0x1a00)
        self.assertEqual(rec["temperature"], 34)

    def test_negative_temperature(self):
        s = make_sample(0)
        s.temperature = -12
        rec = record.unpack(record.pack(s))
        self.assertEqual(rec["temperature"], -12)

    def test_unpack_rejects_short_buffer(self):
        with self.assertRaises(ValueError):
            record.unpack(b"\0" * 63)

    def test_session_name_is_safe(self):
        name = record.session_name("后坐 试验/1", now=1_700_000_000)
        self.assertNotIn("/", name)
        self.assertNotIn(" ", name)
        self.assertTrue(name.endswith("_后坐试验1") or "后坐" in name)


class TestSessionWriter(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="imu-test-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_write_read_roundtrip(self):
        w = record.SessionWriter(self.root, tag="t", now=1_700_000_000,
                                 streams={"muzzle": {"device": "uuid:TEST"}})
        for i in range(5):
            self.assertTrue(w.append("muzzle", make_sample(i)))
        meta = w.close()
        self.assertEqual(meta["state"], "closed")
        self.assertEqual(meta["streams"]["muzzle"]["frames"], 5)
        self.assertEqual(meta["streams"]["muzzle"]["bytes"], 5 * 64)
        rows = list(record.read_stream(w.dir, "muzzle"))
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["seq"], 0)
        self.assertAlmostEqual(rows[4]["ax"], 0.4, places=5)

    def test_unknown_role_is_ignored(self):
        w = record.SessionWriter(self.root, streams={"muzzle": {}})
        self.assertFalse(w.append("nope", make_sample(0)))
        w.close()

    def test_close_is_idempotent(self):
        w = record.SessionWriter(self.root, streams={"muzzle": {}})
        w.append("muzzle", make_sample(0))
        a = w.close()
        b = w.close()
        self.assertEqual(a["streams"]["muzzle"]["frames"], b["streams"]["muzzle"]["frames"])

    def test_verify_matches_meta(self):
        w = record.SessionWriter(self.root, streams={"muzzle": {}})
        for i in range(3):
            w.append("muzzle", make_sample(i))
        w.close()
        res = record_verify(w.dir, "muzzle")
        self.assertTrue(res["ok"], res["problems"])
        self.assertEqual(res["frames"], 3)


def record_verify(dirpath, role):
    return exporter.verify(dirpath, role)


class TestRing(unittest.TestCase):
    def test_eviction_and_counters(self):
        r = Ring(3)
        for i in range(5):
            r.append(1000 + i, b"x" * 64)
        self.assertEqual(len(r), 3)
        self.assertEqual(r.total, 5)
        self.assertEqual(r.dropped, 2)
        self.assertEqual(r.nbytes, 3 * 64)

    def test_last_seconds(self):
        r = Ring(100)
        base = 1_000_000_000
        for i in range(10):
            r.append(base + i * 100_000_000, b"y" * 64)   # 每 0.1 s 一条
        items = r.last(seconds=0.35)
        self.assertEqual(len(items), 4)                    # 0.6/0.7/0.8/0.9 s
        self.assertEqual(items[-1][0], base + 900_000_000)

    def test_span_and_empty(self):
        r = Ring(10)
        self.assertEqual(r.span_s(), 0.0)
        self.assertEqual(r.last(seconds=1), [])
        r.append(0, b"z" * 64)
        r.append(1_000_000_000, b"z" * 64)
        self.assertAlmostEqual(r.span_s(), 1.0)

    def test_multi_ring(self):
        m = MultiRing(2, roles=("muzzle",))
        m.append("muzzle", 1, b"a" * 64)
        m.append("base", 2, b"b" * 64)      # 自动建 base
        self.assertEqual(len(m.last("muzzle")), 1)
        self.assertEqual(len(m.last("base")), 1)
        self.assertEqual(set(m.stats()), {"muzzle", "base"})


class TestQuota(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="imu-quota-")
        self.now = 1_700_000_000.0

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _mk(self, name, age_s, size=100, keep=False, state="closed"):
        path = os.path.join(self.root, name)
        make_meta(path, self.now - age_s, state=state, keep=keep)
        with open(os.path.join(path, "muzzle.bin"), "wb") as fh:
            fh.write(b"\0" * size)
        return path

    def test_usage_counts_only_sessions(self):
        self._mk("a", 3600)
        os.makedirs(os.path.join(self.root, "orphan"))
        u = quota.usage(self.root)
        self.assertGreater(u, 0)
        self.assertEqual(len(quota.list_sessions(self.root)), 1)

    def test_deletes_oldest_first_until_under_quota(self):
        a = self._mk("a", 5000)
        b = self._mk("b", 4000)
        c = self._mk("c", 3000)
        # 配额取「只留 c 刚好够」：期望按创建时间从老到新删掉 a、b
        budget = record.dir_size(c) + 1
        removed = quota.enforce(self.root, quota_bytes=budget, now=self.now, min_age_s=0)
        self.assertEqual(removed, [a, b])
        self.assertTrue(os.path.isdir(c))
        self.assertLessEqual(quota.usage(self.root), budget)

    def test_keep_and_recording_survive(self):
        a = self._mk("a", 9000, keep=True)
        b = self._mk("b", 8000, state="recording")
        c = self._mk("c", 7000)
        removed = quota.enforce(self.root, quota_bytes=0, now=self.now, min_age_s=0)
        self.assertEqual(removed, [c])
        self.assertTrue(os.path.isdir(a))
        self.assertTrue(os.path.isdir(b))

    def test_recent_sessions_survive(self):
        a = self._mk("a", 60)
        removed = quota.enforce(self.root, quota_bytes=0, now=self.now, min_age_s=600)
        self.assertEqual(removed, [])
        self.assertTrue(os.path.isdir(a))

    def test_protected_by_name(self):
        a = self._mk("a", 9000)
        removed = quota.enforce(self.root, quota_bytes=0, now=self.now,
                                min_age_s=0, protected=["a"])
        self.assertEqual(removed, [])
        self.assertTrue(os.path.isdir(a))

    def test_mark_keep(self):
        a = self._mk("a", 10)
        self.assertTrue(quota.mark_keep(a, True))
        self.assertTrue(os.path.exists(os.path.join(a, record.KEEP_NAME)))
        self.assertFalse(quota.mark_keep(a, False))


class TestExporter(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="imu-exp-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_csv_header_and_relative_time(self):
        w = record.SessionWriter(self.root, streams={"muzzle": {}})
        for i in range(4):
            w.append("muzzle", make_sample(i))
        w.close()
        out = os.path.join(self.root, "out.csv")
        n = exporter.export_csv(w.dir, "muzzle", out)
        self.assertEqual(n, 4)
        with open(out, encoding="utf-8") as fh:
            lines = fh.read().strip().split("\n")
        self.assertEqual(lines[0], ",".join(record.CSV_COLUMNS))
        self.assertEqual(len(lines), 5)
        first = lines[1].split(",")
        self.assertAlmostEqual(float(first[0]), 0.0)
        self.assertAlmostEqual(float(lines[2].split(",")[0]), 0.001, places=6)

    def test_jsonl_rows(self):
        w = record.SessionWriter(self.root, streams={"muzzle": {}})
        for i in range(2):
            w.append("muzzle", make_sample(i))
        w.close()
        out = os.path.join(self.root, "out.jsonl")
        self.assertEqual(exporter.export_jsonl(w.dir, "muzzle", out), 2)
        with open(out, encoding="utf-8") as fh:
            rows = [json.loads(x) for x in fh if x.strip()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["seq"], 1)

    def test_verify_flags_truncated_file(self):
        w = record.SessionWriter(self.root, streams={"muzzle": {}})
        w.append("muzzle", make_sample(0))
        w.close()
        with open(os.path.join(w.dir, "muzzle.bin"), "ab") as fh:
            fh.write(b"\0" * 10)
        res = exporter.verify(w.dir, "muzzle")
        self.assertFalse(res["ok"])
        self.assertTrue(any("整数倍" in p for p in res["problems"]))


if __name__ == "__main__":
    unittest.main()
