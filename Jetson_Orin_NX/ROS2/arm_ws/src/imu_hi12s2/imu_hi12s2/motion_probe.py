# -*- coding: utf-8 -*-
"""motion_probe —— 现场核验用的分秒统计探针（M1）。

为什么单独写一个，而不是 imu_identify --listen：
  --listen 把整段样本揉成一个 RMS。如果人只在其中 6 秒晃了臂，
  其余 100 秒静止，聚合 RMS 会被稀释，判别比值变小。
  本工具**按秒分桶**并逐秒落盘，事后挑“比值最大且两路都满帧”的那一秒做判别，
  既不稀释、也不怕中途被打断（每秒刷新文件）。

用法：
    python3 -m imu_hi12s2.motion_probe --seconds 300 --out ~/imu_probe/motion.json

安全：只读设备身份 + 恢复输出流，不写任何设备配置。
"""
import argparse
import json
import os
import time

from imu_core.discriminator import discriminate
from imu_core.registry import enumerate_tty_devices

from .driver import Hi12s2Driver
from .link import detect_baud_on_link


def _open_all(baud_candidates):
    drivers, errors = [], []
    for dev in enumerate_tty_devices():
        try:
            drv = Hi12s2Driver(dev, baud=baud_candidates[0])
            drv.link.open()
        except OSError as exc:
            errors.append((dev, "open 失败（可能 wedged）：%s" % (exc,)))
            continue
        baud, _detail = detect_baud_on_link(drv.link, candidates=baud_candidates)
        if baud is None:
            errors.append((dev, "探测不到可读回包"))
            try:
                drv.close()
            except Exception:
                pass
            continue
        drv.baud = baud
        drv.identify()
        drv.start_stream()
        drivers.append(drv)
    return drivers, errors


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=300.0)
    ap.add_argument("--out", default=os.path.expanduser("~/imu_probe/motion.json"))
    ap.add_argument("--baud", type=int, default=None)
    args = ap.parse_args(argv)

    candidates = [args.baud] if args.baud else [921600, 460800, 230400, 115200]
    drivers, errors = _open_all(candidates)
    if not drivers:
        print("没有可用设备。先跑 hub-first 恢复：")
        print("  cd ~/imu_probe/baseline && echo 1 | sudo -S python3 -u ch340_recover.py")
        for dev, msg in errors:
            print("  %s: %s" % (dev, msg))
        return 2

    keys = [d.device_key() for d in drivers]
    print("已打开 %d 台：%s" % (len(drivers), ", ".join(keys)))
    for dev, msg in errors:
        print("  ⚠ %s: %s" % (dev, msg))

    buckets = {}   # sec_index -> key -> {n, sum_sq, peak}
    t0 = time.monotonic()
    deadline = t0 + args.seconds
    last_flush = 0.0
    state = {"phase": "running"}

    def flush():
        payload = {
            "schema": 1,
            "devices": keys,
            "seconds": round(time.monotonic() - t0, 2),
            "buckets": {str(k): v for k, v in buckets.items()},
            "errors": errors,
            "phase": state["phase"],
        }
        tmp = args.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, args.out)

    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            for drv in drivers:
                for s in drv.read_batch(timeout=0.002):
                    idx = int(s.t_rx_ns / 1e9 - t0)
                    mag = (s.gx * s.gx + s.gy * s.gy + s.gz * s.gz) ** 0.5
                    rec = buckets.setdefault(idx, {}).setdefault(
                        s.device, {"n": 0, "sum_sq": 0.0, "peak": 0.0})
                    rec["n"] += 1
                    rec["sum_sq"] += mag * mag
                    if mag > rec["peak"]:
                        rec["peak"] = mag
            if now - last_flush >= 1.0:
                flush()
                last_flush = now
    except KeyboardInterrupt:
        pass
    finally:
        state["phase"] = "closing"
        flush()
        for drv in drivers:
            try:
                drv.close()
            except Exception:
                pass
        state["phase"] = "done"
        flush()

    # 分秒统计 + 挑最佳窗口
    rows = []
    for idx in sorted(buckets):
        row = {"sec": idx}
        for key, rec in buckets[idx].items():
            row[key] = {
                "n": rec["n"],
                "rms_dps": (rec["sum_sq"] / rec["n"]) ** 0.5 if rec["n"] else 0.0,
                "peak_dps": rec["peak"],
            }
        rows.append(row)

    print("\n秒  " + "  ".join("%-30s" % k for k in keys))
    for row in rows:
        cells = []
        for key in keys:
            item = row.get(key)
            cells.append("%8s" % ("-" if item is None else "%.2f/%d" % (item["rms_dps"], item["n"])))
        print("%3d  %s" % (row["sec"], "  ".join(cells)))

    # 候选秒：两路都有 >=60% 满帧（1000 Hz -> 600 帧）
    best = None
    for row in rows:
        stats = {}
        ok = True
        for key in keys:
            item = row.get(key)
            if item is None or item["n"] < 600:
                ok = False
                break
            stats[key] = {"frames": item["n"], "rms_dps": item["rms_dps"], "peak_dps": item["peak_dps"]}
        if not ok:
            continue
        res = discriminate(stats, min_frames=600)
        if not res.ok:
            continue
        top = max(res.ratios, key=res.ratios.get)
        ratio = res.ratios[top] / max(min(res.ratios.values()), 0.02)
        if best is None or ratio > best[1]:
            best = (row["sec"], ratio, res)

    if best:
        sec, ratio, res = best
        print("\n最佳窗口：第 %d 秒，比值 %.1fx，confidence=%.2f" % (sec, ratio, res.confidence))
        for key, role in res.roles.items():
            print("  %s -> %s" % (key, role))
    else:
        print("\n没有找到可判别的窗口（两路都太静或都太像）。再动大一点、久一点。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
