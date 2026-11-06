# -*- coding: utf-8 -*-
"""imu_core 单元测试（纯逻辑，不需要硬件，Windows/Jetson 都能跑）。

跑法：cd src/imu_core && python3 -m unittest discover -s test -v
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from imu_core import (  # noqa: E402
    DeviceIdentity,
    IDENTITY_USB_PATH,
    IDENTITY_UUID,
    Quality,
    Roster,
    ROLE_BASE,
    ROLE_MUZZLE,
    ROLE_UNASSIGNED,
    WindowQuality,
    assign_roles,
    discriminate,
    motion_stats,
)
from imu_core.discriminator import DiscriminatorResult  # noqa: E402
from imu_core.types import ImuSample, decode_status  # noqa: E402


def make_sample(key, t_ns, gx=0.0, gy=0.0, gz=0.0, status=0x1A00):
    return ImuSample(
        t_rx_ns=t_ns, device=key, role="unassigned", t_sys_ms=0,
        ax=0.0, ay=0.0, az=1.0, gx=gx, gy=gy, gz=gz,
        roll=0.0, pitch=0.0, yaw=0.0, qw=1.0, qx=0.0, qy=0.0, qz=0.0,
        temperature=30.0, status=status,
    )


class TestIdentity(unittest.TestCase):
    def test_uuid_is_strong(self):
        ident = DeviceIdentity(IDENTITY_UUID, "24B4EB573C480701", model="HI12S2-MI1-000")
        self.assertFalse(ident.weak)
        self.assertEqual(ident.key, "uuid:24B4EB573C480701")

    def test_port_is_weak(self):
        ident = DeviceIdentity(IDENTITY_USB_PATH, "1-3.3.1")
        self.assertTrue(ident.weak)
        self.assertEqual(ident.key, "usb_path:1-3.3.1")


class TestRoster(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="imu_roster_")
        self.path = os.path.join(self.tmp, "imu_roles.json")

    def tearDown(self):
        for name in os.listdir(self.tmp):
            os.unlink(os.path.join(self.tmp, name))
        os.rmdir(self.tmp)

    def test_missing_file_is_empty_roster(self):
        roster = Roster.load(self.path)
        ident = DeviceIdentity(IDENTITY_UUID, "AAA")
        self.assertEqual(roster.resolve(ident), (ROLE_UNASSIGNED, "unassigned"))

    def test_bind_and_reload(self):
        roster = Roster.load(self.path)
        a = DeviceIdentity(IDENTITY_UUID, "AAA", model="HI12S2-MI1-000", usb_path="1-3.3.1")
        b = DeviceIdentity(IDENTITY_UUID, "BBB", model="HI12S2-MI1-000", usb_path="1-3.3.2")
        roster.bind(a, ROLE_BASE)
        roster.bind(b, ROLE_MUZZLE)
        roster.save()

        again = Roster.load(self.path)
        self.assertEqual(again.resolve(a)[0], ROLE_BASE)
        self.assertEqual(again.resolve(b)[0], ROLE_MUZZLE)
        self.assertEqual(again.resolve(a)[1], "roster")

    def test_port_fallback_survives_swapped_uuid(self):
        roster = Roster.load(self.path)
        roster.bind(DeviceIdentity(IDENTITY_USB_PATH, "1-3.3.1"), ROLE_BASE)
        roster.save()
        again = Roster.load(self.path)
        # 换了模块但插口没变：弱身份按端口认出基座
        swapped = DeviceIdentity(IDENTITY_UUID, "CCC", usb_path="1-3.3.1")
        self.assertEqual(again.resolve(swapped)[0], ROLE_BASE)
        self.assertEqual(again.resolve(swapped)[1], "usb_path(weak)")

    def test_bad_role_rejected(self):
        roster = Roster.load(self.path)
        with self.assertRaises(Exception):
            roster.bind(DeviceIdentity(IDENTITY_UUID, "AAA"), "gunner")

    def test_file_is_valid_json(self):
        roster = Roster.load(self.path)
        roster.bind(DeviceIdentity(IDENTITY_UUID, "AAA"), ROLE_BASE)
        roster.save()
        with open(self.path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["schema"], 1)
        self.assertIn("AAA", data["devices"])


class TestQuality(unittest.TestCase):
    def test_status_1a00(self):
        q = Quality.from_status(0x1A00)
        self.assertFalse(q.acc_sat)
        self.assertFalse(q.gyr_sat)
        self.assertTrue(q.static)
        self.assertTrue(q.utc_unsync)
        self.assertTrue(q.sout_pulse)
        self.assertTrue(q.usable_for_transient)

    def test_saturation_blocks_transient(self):
        q = Quality.from_status(1 << 6)
        self.assertTrue(q.gyr_sat)
        self.assertFalse(q.usable_for_transient)

    def test_decode_status_names(self):
        self.assertEqual(decode_status(0x1A00), ("static", "utc_unsync", "sout_pulse"))

    def test_window_quality(self):
        w = WindowQuality(window_s=1.0)
        for i in range(10):
            w.update(i * 10_000_000, 0x1A00)
        snap = w.snapshot()
        self.assertEqual(snap["frames"], 10)
        self.assertAlmostEqual(snap["static"], 1.0)
        self.assertAlmostEqual(snap["gyr_sat"], 0.0)


class TestDiscriminator(unittest.TestCase):
    def test_clear_motion_picks_muzzle(self):
        samples = []
        for i in range(200):
            samples.append(make_sample("uuid:M", i * 1_000_000, gx=1.0))
            samples.append(make_sample("uuid:B", i * 1_000_000, gx=0.05))
        stats = motion_stats(samples)
        res = discriminate(stats)
        self.assertTrue(res.ok)
        self.assertEqual(res.roles["uuid:M"], ROLE_MUZZLE)
        self.assertEqual(res.roles["uuid:B"], ROLE_BASE)

    def test_both_still_is_not_guessed(self):
        samples = []
        for i in range(200):
            samples.append(make_sample("uuid:M", i * 1_000_000, gx=0.01))
            samples.append(make_sample("uuid:B", i * 1_000_000, gx=0.01))
        res = discriminate(motion_stats(samples))
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "both-still")
        self.assertEqual(res.roles, {})

    def test_ambiguous_ratio_rejected(self):
        samples = []
        for i in range(200):
            samples.append(make_sample("uuid:A", i * 1_000_000, gx=1.0))
            samples.append(make_sample("uuid:B", i * 1_000_000, gx=0.8))
        res = discriminate(motion_stats(samples))
        self.assertFalse(res.ok)
        self.assertTrue(res.reason.startswith("ambiguous"))

    def test_insufficient_data(self):
        samples = [make_sample("uuid:A", i * 1_000_000, gx=1.0) for i in range(5)]
        res = discriminate(motion_stats(samples))
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "insufficient-data")


class TestAssignRoles(unittest.TestCase):
    def test_unassigned_still_reported(self):
        roster = Roster()
        ids = [DeviceIdentity(IDENTITY_UUID, "AAA")]
        result = assign_roles(ids, roster)
        self.assertEqual(result.assignments[0].role, ROLE_UNASSIGNED)
        self.assertTrue(any("未登记" in w for w in result.warnings))

    def test_weak_identity_warns(self):
        roster = Roster()
        ids = [DeviceIdentity(IDENTITY_USB_PATH, "1-3.3.1")]
        result = assign_roles(ids, roster)
        self.assertTrue(any("弱身份" in w for w in result.warnings))

    def test_duplicate_role_warns(self):
        roster = Roster()
        a = DeviceIdentity(IDENTITY_UUID, "AAA")
        b = DeviceIdentity(IDENTITY_UUID, "BBB")
        roster.bind(a, ROLE_BASE)
        roster.bind(b, ROLE_BASE)
        result = assign_roles([a, b], roster)
        self.assertTrue(any("被多台" in w for w in result.warnings))

    def test_proposal_not_adopted_by_default(self):
        roster = Roster()
        ids = [DeviceIdentity(IDENTITY_UUID, "AAA"), DeviceIdentity(IDENTITY_UUID, "BBB")]
        samples = []
        for i in range(200):
            samples.append(make_sample("uuid:AAA", i * 1_000_000, gx=1.0))
            samples.append(make_sample("uuid:BBB", i * 1_000_000, gx=0.05))
        result = assign_roles(ids, roster, stats=motion_stats(samples))
        self.assertTrue(result.proposal.ok)
        # 默认不采纳：仍然是 unassigned，只给建议
        self.assertEqual(result.role_of("uuid:AAA"), ROLE_UNASSIGNED)
        self.assertTrue(any("动臂判别建议" in w for w in result.warnings))

    def test_auto_discriminate_adopts(self):
        roster = Roster()
        ids = [DeviceIdentity(IDENTITY_UUID, "AAA"), DeviceIdentity(IDENTITY_UUID, "BBB")]
        samples = []
        for i in range(200):
            samples.append(make_sample("uuid:AAA", i * 1_000_000, gx=1.0))
            samples.append(make_sample("uuid:BBB", i * 1_000_000, gx=0.05))
        result = assign_roles(ids, roster, stats=motion_stats(samples), auto_discriminate=True)
        self.assertEqual(result.role_of("uuid:AAA"), ROLE_MUZZLE)
        self.assertEqual(result.role_of("uuid:BBB"), ROLE_BASE)


if __name__ == "__main__":
    unittest.main()
