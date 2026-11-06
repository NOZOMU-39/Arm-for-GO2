#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 基线长测：双路 HI12S2 同时按 1000 Hz 连续采集，产出可复现的验收报告。

用法（Jetson 上）：
    python3 baseline_run.py --duration 1800 --json-out /tmp/imu_baseline.json
    python3 baseline_run.py --duration 60            # 快速自检
    python3 baseline_run.py --ports /dev/ttyUSB0,/dev/ttyUSB1 --duration 60

验收判据（P0）：
    1. 每路 fps >= 999.5
    2. 每路 system_time 相邻步长恒为 1 ms（这是手册认可的真丢帧判据）
    3. 每路 CRC 坏帧 == 0

收尾后会做一次"关完再开"探测：CH340 有满速后 close 即 wedged 的已知缺陷，
所以探测失败不算测量失败，但必须记录，并交给 ch340_recover.py 处置。
"""

import argparse
import faulthandler
import json
import os
import select
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hi12_link import (  # noqa: E402
    FrameSplitter,
    Hi12Link,
    crc_selftest,
    decode_status,
    detect_baud_on_link,
    list_tty_usb,
    parse_091,
    probe_open,
    usb_port_of,
)

STOP = {"flag": False}


def _on_sigint(_signum, _frame):
    STOP["flag"] = True


def _welford(n, mean, m2, x):
    n += 1
    delta = x - mean
    mean += delta / n
    m2 += delta * (x - mean)
    return n, mean, m2


class PortStats(object):
    """单口的采集统计。只存聚合量，不存原始帧（1800 s x 1000 Hz x 2 路 = 360 万帧）。"""

    def __init__(self, dev, baud):
        self.dev = dev
        self.baud = baud
        self.usb_port = usb_port_of(dev)
        self.uuid = None
        self.pname = None
        self.sn = None
        self.version_raw = ""
        self.frames = 0
        # 链路质量
        self.crc_bad = 0
        self.resync_bytes = 0
        self.len_bad = 0
        self.reads = 0
        self.read_bytes = 0
        self.read_dt_n = 0
        self.read_dt_mean = 0.0
        self.read_dt_m2 = 0.0
        self.read_dt_max = 0.0
        # system_time 步长（真丢帧判据）
        self.sys_prev = None
        self.sys_steps = {}
        self.sys_wrap = 0
        self.sys_anomaly = 0
        self.sys_max_step = 0
        # 信号
        self.acc_sum = [0.0, 0.0, 0.0]
        self.acc_sq = [0.0, 0.0, 0.0]
        self.gyr_sum = [0.0, 0.0, 0.0]
        self.gyr_sq = [0.0, 0.0, 0.0]
        self.anorm_min = None
        self.anorm_max = None
        self.wnorm_min = None
        self.wnorm_max = None
        self.temp = None
        self.euler = None
        self.quat = None
        self.status = {}
        self.sat_acc = 0
        self.sat_gyr = 0

    # -- 每帧

    def add(self, d):
        self.frames += 1
        if self.frames == 1:
            self.t_first_frame = None  # 由外部持有 t0
        st = d["system_time"]
        if self.sys_prev is None:
            self.sys_prev = st
        else:
            step = (st - self.sys_prev) & 0xFFFFFFFF
            self.sys_prev = st
            if step > 0x80000000:          # 反向 -> 视为回绕
                self.sys_wrap += 1
            else:
                if len(self.sys_steps) < 64 or step in self.sys_steps:
                    self.sys_steps[step] = self.sys_steps.get(step, 0) + 1
                else:
                    self.sys_steps["other"] = self.sys_steps.get("other", 0) + 1
                if step != 1:
                    self.sys_anomaly += 1
                if step > self.sys_max_step:
                    self.sys_max_step = step

        ax, ay, az = d["ax"], d["ay"], d["az"]
        gx, gy, gz = d["gx"], d["gy"], d["gz"]
        for k, v in enumerate((ax, ay, az)):
            self.acc_sum[k] += v
            self.acc_sq[k] += v * v
        for k, v in enumerate((gx, gy, gz)):
            self.gyr_sum[k] += v
            self.gyr_sq[k] += v * v
        an = (ax * ax + ay * ay + az * az) ** 0.5
        wn = (gx * gx + gy * gy + gz * gz) ** 0.5
        if self.anorm_min is None or an < self.anorm_min:
            self.anorm_min = an
        if self.anorm_max is None or an > self.anorm_max:
            self.anorm_max = an
        if self.wnorm_min is None or wn < self.wnorm_min:
            self.wnorm_min = wn
        if self.wnorm_max is None or wn > self.wnorm_max:
            self.wnorm_max = wn

        mstatus = d["main_status"]
        self.status[mstatus] = self.status.get(mstatus, 0) + 1
        if mstatus & (1 << 5):
            self.sat_acc += 1
        if mstatus & (1 << 6):
            self.sat_gyr += 1
        self.temp = d["temperature"]
        self.euler = (d["roll"], d["pitch"], d["yaw"])
        self.quat = (d["qw"], d["qx"], d["qy"], d["qz"])

    # -- 汇总

    def summary(self, duration):
        n = max(self.frames, 1)
        out = {
            "dev": self.dev,
            "baud": self.baud,
            "usb_port": self.usb_port,
            "uuid": self.uuid,
            "pname": self.pname,
            "sn": self.sn,
            "frames": self.frames,
            "duration_s": round(duration, 3),
            "fps": round(self.frames / duration, 3) if duration > 0 else 0.0,
            "crc_bad": self.crc_bad,
            "resync_bytes": self.resync_bytes,
            "len_bad": self.len_bad,
            "reads": self.reads,
            "read_bytes": self.read_bytes,
            "read_dt_ms_mean": round(1e3 * self.read_dt_mean, 4),
            "read_dt_ms_max": round(1e3 * self.read_dt_max, 4),
            "sys_steps": {str(k): v for k, v in self.sys_steps.items()},
            "sys_wrap": self.sys_wrap,
            "sys_anomaly": self.sys_anomaly,
            "sys_max_step_ms": self.sys_max_step,
            "temp_c": self.temp,
            "acc_mean_g": [round(v / n, 6) for v in self.acc_sum],
            "acc_sd_g": [round((max(self.acc_sq[k] / n - (self.acc_sum[k] / n) ** 2, 0.0)) ** 0.5, 6)
                         for k in range(3)],
            "gyr_mean_dps": [round(v / n, 6) for v in self.gyr_sum],
            "gyr_sd_dps": [round((max(self.gyr_sq[k] / n - (self.gyr_sum[k] / n) ** 2, 0.0)) ** 0.5, 6)
                           for k in range(3)],
            "anorm_g_range": [round(self.anorm_min or 0, 6), round(self.anorm_max or 0, 6)],
            "wnorm_dps_range": [round(self.wnorm_min or 0, 6), round(self.wnorm_max or 0, 6)],
            "euler_deg": [round(v, 3) for v in self.euler] if self.euler else None,
            "quat_wxyz": [round(v, 5) for v in self.quat] if self.quat else None,
            "main_status": {hex(k): v for k, v in self.status.items()},
            "status_bits": sorted({b for k in self.status for b in decode_status(k)}),
            "sat_acc_frames": self.sat_acc,
            "sat_gyr_frames": self.sat_gyr,
        }
        return out


def _identity(link, st, ontime):
    """静音 -> 查 UUID -> 恢复输出。"""
    kv, raw = link.query_version()
    st.uuid = kv.get("UUID")
    st.pname = kv.get("PNAME")
    st.sn = kv.get("SN")
    st.version_raw = raw.strip()
    link.unmute(ontime=ontime)
    return kv


def main(argv=None):
    ap = argparse.ArgumentParser(description="HI12S2 双路基线长测")
    ap.add_argument("--duration", type=float, default=1800.0, help="采集时长（秒）")
    ap.add_argument("--baud", default="auto", help="921600 / 460800 / 115200 / auto（默认自动探测）")
    ap.add_argument("--ontime", default="0.001", help="恢复 0x91 输出的周期（秒）")
    ap.add_argument("--ports", default="", help="逗号分隔的串口，默认自动发现 /dev/ttyUSB*")
    ap.add_argument("--json-out", default="", help="报告 JSON 输出路径")
    ap.add_argument("--min-fps", type=float, default=999.5)
    ap.add_argument("--log-every", type=float, default=60.0)
    ap.add_argument("--no-query", action="store_true", help="跳过 UUID/配置查询")
    ap.add_argument("--watchdog", type=float, default=0.0,
                    help="卡死看门狗：每 N 秒把当前调用栈打到 stderr（0=关闭）")
    args = ap.parse_args(argv)

    if args.watchdog > 0:
        faulthandler.dump_traceback_later(args.watchdog, repeat=True)

    if not crc_selftest():
        print("FATAL: CRC-16/XMODEM 自检失败，拒绝继续")
        return 2
    signal.signal(signal.SIGINT, _on_sigint)

    devs = [d.strip() for d in args.ports.split(",") if d.strip()] or list_tty_usb()
    if not devs:
        print("FATAL: 没有发现任何 /dev/ttyUSB*，请检查 IMU 是否插上")
        return 2

    print("=" * 78)
    print("HI12S2 基线长测  duration=%.1fs  baud=%s  ports=%s" % (args.duration, args.baud, devs))
    print("=" * 78)

    links, stats = [], []
    try:
        for dev in devs:
            link = Hi12Link(dev, 921600)      # 初始值无所谓；auto 模式下随后会被改
            try:
                link.open()
            except OSError as exc:
                print("!! %s 打不开: %s" % (dev, exc))
                print("   -> 先跑 ch340_recover.py 恢复芯片，再重试")
                return 3
            if args.baud == "auto":
                print("[..] %s 探测波特率中 ..." % dev, flush=True)
                best, detail = detect_baud_on_link(link)
                chain = "; ".join("%d:%s" % (b, note) for b, note in detail)
                if best is None:
                    print("!! %s 在所有候选波特率下都没有有效回包：%s" % (dev, chain))
                    print("   -> 先跑 ch340_recover.py；若端口正常，可能模块未上电或线序不对")
                    link.quiet_close()
                    return 3
                print("[baud] %-14s -> %d   (%s)" % (dev, best, chain))
            else:
                link.set_baud(int(args.baud))
            st = PortStats(dev, link.baud)
            if not args.no_query:
                print("[..] %s 查询 UUID 中 ..." % dev, flush=True)
                kv = _identity(link, st, args.ontime)
                print("[id] %-14s usb=%-10s UUID=%-18s SN=%-16s PNAME=%s"
                      % (dev, st.usb_port, st.uuid, st.sn or "(空)", st.pname))
                if not st.uuid:
                    print("     !! 没解析到 UUID，原始回包：")
                    for line in st.version_raw.splitlines()[:6]:
                        print("        | " + line)
            links.append(link)
            stats.append(st)

        # ---- 健康期缓存拓扑（设备掉出总线后恢复的唯一线索）
        # 放在这里的原因：此刻两个口刚 open 成功、sysfs 完整，
        # 是「口 -> 祖先 HUB 链」最可信的时刻。
        try:
            import ch340_recover as _rec
            _rec.save_topology(ports=devs)
        except Exception as exc:                    # 缓存失败不影响本次采集
            print("[cache] 拓扑缓存写入失败（不影响采集）: %s" % (exc,))

        # ---- 采集主循环
        fdmap = {link.fd: (link, st, FrameSplitter()) for link, st in zip(links, stats)}
        fds = list(fdmap)
        # 【必须做】在 t0 之前把所有口的输入队列清空。
        # 否则先配置好的那台在等着配置第二台的这几秒里一直往内核缓冲里塞帧，
        # 主循环一开就把它当"本次采集到的"吃掉，帧数虚高到 1115 fps（实测踩到）。
        for link in links:
            link.flush()
        t0 = time.monotonic()
        t_end = t0 + args.duration
        last_log = t0
        read_prev = {}
        while time.monotonic() < t_end and not STOP["flag"]:
            try:
                r, _, _ = select.select(fds, [], [], 0.5)
            except (OSError, ValueError) as exc:
                print("!! select 异常: %s" % (exc,))
                break
            now = time.monotonic()
            for fd in r:
                try:
                    data = os.read(fd, 262144)
                except OSError as exc:
                    print("!! read %s: %s" % (fd, exc))
                    continue
                if not data:
                    continue
                _link, st, split = fdmap[fd]
                st.reads += 1
                st.read_bytes += len(data)
                prev = read_prev.get(fd)
                if prev is not None:
                    st.read_dt_n, st.read_dt_mean, st.read_dt_m2 = _welford(
                        st.read_dt_n, st.read_dt_mean, st.read_dt_m2, now - prev)
                    if now - prev > st.read_dt_max:
                        st.read_dt_max = now - prev
                read_prev[fd] = now
                for payload in split.feed(data):
                    st.add(parse_091(payload))
            if now - last_log >= args.log_every:
                last_log = now
                el = now - t0
                print("[t=%6.1fs] " % el + "  ".join(
                    "%s:%d" % (os.path.basename(s.dev), s.frames) for s in stats))
                sys.stdout.flush()

        duration = time.monotonic() - t0

        # ---- 收尾：静音 -> 排空 -> close
        for link in links:
            link.quiet_close()
        links = []

        # ---- 报告（先出结果，再做可能触发 wedge 的探测——探测失败不能把报告弄丢）
        time.sleep(1.0)
        summaries = [st.summary(duration) for st in stats]
        unit_ok = all(s["sys_anomaly"] == 0 and s["sys_wrap"] == 0 for s in summaries)
        fps_ok = all(s["fps"] >= args.min_fps for s in summaries)
        crc_ok = all(s["crc_bad"] == 0 for s in summaries)
        overall = unit_ok and fps_ok and crc_ok

        print("")
        print("-" * 78)
        print("%-10s %8s %10s %9s %8s %10s %s" %
              ("port", "frames", "fps", "crc_bad", "sys_anom", "max_step", "usb_port"))
        for s in summaries:
            print("%-10s %8d %10.3f %9d %8d %10d %s" %
                  (os.path.basename(s["dev"]), s["frames"], s["fps"],
                   s["crc_bad"], s["sys_anomaly"], s["sys_max_step_ms"], s["usb_port"]))
        print("-" * 78)
        print("fps>=%.1f: %s | sys_time 恒 1ms: %s | CRC 0 错: %s => %s"
              % (args.min_fps, "PASS" if fps_ok else "FAIL",
                 "PASS" if unit_ok else "FAIL",
                 "PASS" if crc_ok else "FAIL",
                 "PASS" if overall else "FAIL"))

        # ---- 关完再开探测（CH340 满速收流后 close 即 wedged 的已知缺陷）
        probes = {}
        for dev in devs:
            ok, detail = probe_open(dev, timeout=3.0)
            probes[dev] = {"open_ok": ok, "detail": detail}
            print("[probe] %-14s reopen %s %s" % (
                dev, "OK" if ok else "FAIL", detail), flush=True)

        report = {
            "schema": "imu-baseline-v1",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "duration_s": round(duration, 3),
            "baud_requested": args.baud,
            "ontime": args.ontime,
            "target_fps": round(1.0 / float(args.ontime), 3) if float(args.ontime) > 0 else None,
            "ports": summaries,
            "probe_after_close": probes,
            "verdict": {
                "fps_ok": fps_ok,
                "sys_time_unit_ok": unit_ok,
                "crc_ok": crc_ok,
                "overall": "PASS" if overall else "FAIL",
            },
            "host": {"uname": os.uname().sysname + " " + os.uname().release},
        }
        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2)
            print("[json] written to %s" % args.json_out)
        return 0 if overall else 1
    finally:
        for link in links:
            try:
                link.quiet_close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
