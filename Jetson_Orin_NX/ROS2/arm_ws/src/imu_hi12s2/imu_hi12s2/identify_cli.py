# -*- coding: utf-8 -*-
"""imu_identify —— 认设备、派岗位、做现场核验的命令行工具。

这是 M1“身份体系”的落地入口，回答那个老问题：
    “任意插用什么方法能确定它俩谁是谁？”
答案：问 UUID -> 查花名册；没有花名册就现场判别（动一下臂）再把结果写回去。

常用：
    imu_identify                          # 扫一遍，列出 tty/UUID/岗位
    imu_identify --listen 10              # 再采 10 s，给出动臂判别建议
    imu_identify --listen 10 --auto-discriminate   # 采纳判别结果（仍不入册）
    imu_identify --bind uuid:24B4EB573C480701=base # 固化到花名册
    imu_identify --json                   # 机器可读

安全：本工具只读设备身份，**不改任何设备配置**（不写波特率、不改输出周期），
唯一写操作是你显式 --bind 时的花名册文件。
"""
import argparse
import json
import os
import sys
import time

from imu_core.discriminator import motion_stats
from imu_core.registry import assign_roles, enumerate_tty_devices, usb_path_of
from imu_core.roster import ROLE_UNASSIGNED, ROLES, Roster, RosterError

from .driver import Hi12s2Driver
from .link import detect_baud_on_link

DEFAULT_ROSTER = os.path.join(os.path.expanduser("~"), ".config", "imu", "imu_roles.json")


def _open_and_identify(dev, baud_candidates):
    """打开一台设备并认身份。返回 (driver, baud, note)；失败返回 (None, None, 错误串)。"""
    try:
        drv = Hi12s2Driver(dev, baud=baud_candidates[0])
        drv.link.open()
    except OSError as exc:
        return None, None, "打不开（可能已 wedged）：%s" % (exc,)
    try:
        baud, detail = detect_baud_on_link(drv.link, candidates=baud_candidates)
        if baud is None:
            drv.close()
            return None, None, "五个波特率都问不出 LOG VERSION：%s" % (detail,)
        drv.baud = baud
        ident = drv.identify()
        return drv, baud, ident
    except Exception as exc:                      # noqa: BLE001 - CLI 兜底
        try:
            drv.close()
        except Exception:
            pass
        return None, None, "识别异常：%s" % (exc,)


def _listen(drivers, seconds):
    """让已打开的设备一起收 N 秒（先恢复输出），返回样本列表。"""
    for drv in drivers:
        drv.start_stream()
    deadline = time.monotonic() + seconds
    samples = []
    while time.monotonic() < deadline:
        for drv in drivers:
            samples.extend(drv.read_batch(timeout=0.002))
    for drv in drivers:
        drv.stop_stream()
    return samples


def main(argv=None):
    parser = argparse.ArgumentParser(description="识别 IMU 身份并派岗位（M1）")
    parser.add_argument("--roster", default=DEFAULT_ROSTER, help="花名册路径（默认 %(default)s）")
    parser.add_argument("--pattern", default="/dev/ttyUSB*", help="设备通配（默认 %(default)s）")
    parser.add_argument("--baud", type=int, default=None, help="固定波特率（默认自动探测）")
    parser.add_argument("--listen", type=float, default=0.0, help="额外采集秒数，用于动臂判别")
    parser.add_argument("--auto-discriminate", action="store_true", help="采纳动臂判别结果（不写入花名册）")
    parser.add_argument("--bind", action="append", default=[], metavar="KEY=ROLE",
                        help="把设备绑到岗位，KEY 形如 uuid:XXXX 或 usb_path:1-3.3.1")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    devices = enumerate_tty_devices(args.pattern)
    if not devices:
        print("没有找到设备（%s）。检查：USB 是否插好、ls /dev/ttyUSB*" % args.pattern)
        return 2

    roster = Roster.load(args.roster)
    baud_candidates = [args.baud] if args.baud else [921600, 460800, 230400, 115200]

    drivers, reports = [], []
    for dev in devices:
        drv, baud, info = _open_and_identify(dev, baud_candidates)
        if drv is None:
            reports.append({"dev": dev, "usb_path": usb_path_of(dev), "error": info})
            continue
        ident = info
        drivers.append(drv)
        reports.append({
            "dev": dev,
            "usb_path": usb_path_of(dev),
            "baud": baud,
            "key": ident.key,
            "kind": ident.kind,
            "weak": ident.weak,
            "uuid": ident.value if ident.kind == "uuid" else "",
            "model": ident.model,
            "serial": ident.serial,
            "build": ident.build,
        })

    stats = None
    if args.listen > 0 and drivers:
        samples = _listen(drivers, args.listen)
        stats = motion_stats(samples)

    for drv in drivers:
        try:
            drv.close()
        except Exception:
            pass

    identities = [d.identify() for d in drivers]
    result = assign_roles(
        identities, roster, stats=stats, auto_discriminate=args.auto_discriminate
    )
    role_by_key = {a.identity.key: (a.role, a.source) for a in result.assignments}

    for rep in reports:
        if "error" in rep:
            continue
        role, source = role_by_key.get(rep["key"], (ROLE_UNASSIGNED, "unassigned"))
        rep["role"] = role
        rep["role_source"] = source

    # --bind 写花名册
    bound = []
    if args.bind:
        by_key = {a.identity for a in result.assignments}
        lookup = {i.key: i for i in by_key}
        for item in args.bind:
            if "=" not in item:
                print("--bind 需要 KEY=ROLE，收到 %r" % item, file=sys.stderr)
                return 2
            key, role = item.rsplit("=", 1)
            if role not in ROLES:
                print("未知岗位 %r（可选 %s）" % (role, ", ".join(ROLES)), file=sys.stderr)
                return 2
            ident = lookup.get(key)
            if ident is None:
                print("本次没扫到 %r，不能凭空绑定（先插上再跑）" % key, file=sys.stderr)
                return 2
            roster.bind(ident, role)
            bound.append((key, role))
        try:
            roster.save()
        except RosterError as exc:
            print("花名册保存失败：%s" % exc, file=sys.stderr)
            return 2

    if args.json:
        print(json.dumps({
            "roster": args.roster,
            "devices": reports,
            "warnings": result.warnings,
            "proposal": None if result.proposal is None else {
                "ok": result.proposal.ok,
                "reason": result.proposal.reason,
                "confidence": result.proposal.confidence,
                "roles": result.proposal.roles,
                "ratios": result.proposal.ratios,
            },
            "bound": bound,
            "motion_stats": stats,
        }, ensure_ascii=False, indent=2))
        return 0

    print("花名册：%s%s" % (args.roster, "" if os.path.exists(args.roster) else "（不存在，视为空册）"))
    print("")
    header = "%-14s %-11s %-22s %-8s %-10s %s" % ("设备", "USB口", "身份", "波特率", "岗位", "来源")
    print(header)
    print("-" * len(header))
    for rep in reports:
        if "error" in rep:
            print("%-14s %-11s %s" % (rep["dev"].replace("/dev/", ""), rep.get("usb_path") or "-", rep["error"]))
            continue
        print("%-14s %-11s %-22s %-8s %-10s %s" % (
            rep["dev"].replace("/dev/", ""),
            rep["usb_path"] or "-",
            rep["key"],
            rep["baud"],
            rep.get("role", "-"),
            rep.get("role_source", "-"),
        ))
    if stats:
        print("")
        print("运动统计（%.1f s 采集）：" % args.listen)
        for key, st in sorted(stats.items()):
            print("  %-22s 帧=%d  rms=%.3f dps  峰值=%.3f dps  时长=%.2f s" % (
                key, st["frames"], st["rms_dps"], st["peak_dps"], st["duration_s"]))
    if result.warnings:
        print("")
        for line in result.warnings:
            print("⚠ %s" % line)
    if bound:
        print("")
        for key, role in bound:
            print("已绑定：%s -> %s" % (key, role))
    return 0


if __name__ == "__main__":
    sys.exit(main())
