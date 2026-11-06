# -*- coding: utf-8 -*-
"""imu_ctl：与常驻采集进程（daemon.py）对话的命令行。

用法：
    python3 -m imu_hi12s2.ctl status
    python3 -m imu_hi12s2.ctl record start --tag 后坐试验1
    python3 -m imu_hi12s2.ctl record stop
    python3 -m imu_hi12s2.ctl dump --last 30
    python3 -m imu_hi12s2.ctl sessions
    python3 -m imu_hi12s2.ctl keep <目录名> [--unkeep]
    python3 -m imu_hi12s2.ctl quota
    python3 -m imu_hi12s2.ctl rescan
    python3 -m imu_hi12s2.ctl shutdown

加 --json 直接打印原始应答（给脚本用）。
"""
import argparse
import json
import os
import socket
import sys

DEFAULT_SOCKET = "~/.local/share/imu/ctl.sock"


def call(cmd, socket_path=None, timeout=30.0, **kwargs):
    path = os.path.expanduser(socket_path or DEFAULT_SOCKET)
    req = {"cmd": cmd}
    req.update(kwargs)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path)
        s.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    except FileNotFoundError:
        raise SystemExit("连不上 %s：常驻进程没在跑？先启动 imu_hi12s2.daemon" % path)
    except socket.timeout:
        raise SystemExit("等待 %s 应答超时（%ss）" % (path, timeout))
    finally:
        s.close()
    return json.loads(buf.decode("utf-8"))


def _human(resp):
    if not resp.get("ok"):
        return "失败：%s" % resp.get("error")
    if "devices" in resp and "ring" in resp:      # status
        lines = ["运行 %ss  pid=%s  录制=%s  用量=%.1f MB / %.1f GB"
                 % (resp["uptime_s"], resp["pid"],
                    resp["record"].get("dir", "off") if resp["recording"] else "off",
                    resp["usage_bytes"] / 1e6, resp["quota_gb"])]
        for d in resp["devices"]:
            drv = d.get("driver") or {}
            lines.append("  %-14s %-10s %-11s frames=%-9d crc_bad=%s reconnects=%d %s"
                         % (d["dev"], d["role"], d["state"], d["frames"],
                            drv.get("crc_bad"), d["reconnects"],
                            ("err=" + d["last_error"]) if d["last_error"] else ""))
        for role, st in sorted((resp.get("ring") or {}).items()):
            lines.append("  ring %-8s %5d/%d 条  覆盖 %.1f s" % (role, st["n"], st["cap"], st["span_s"]))
        return "\n".join(lines)
    if "sessions" in resp:
        rows = ["%-34s %9s %6s %s" % ("目录", "字节", "帧", "标记")]
        for s in resp["sessions"]:
            rows.append("%-34s %9d %6d %s%s" % (s["name"], s["size"], s["frames"],
                                                "KEEP " if s["keep"] else "", s["state"]))
        return "\n".join(rows) if resp["sessions"] else "还没有录制目录"
    if "frames" in resp and "dir" in resp:
        return "已写入 %s（%s 秒，%s）" % (resp["dir"], resp.get("seconds"), resp.get("frames"))
    if "dir" in resp:
        return "OK %s" % resp["dir"]
    return json.dumps(resp, ensure_ascii=False, indent=2)


def main(argv=None):
    ap = argparse.ArgumentParser(description="IMU 常驻采集控制")
    ap.add_argument("--socket", default=None)
    ap.add_argument("--json", action="store_true", help="打印原始 JSON")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("status")
    sub.add_parser("sessions")
    sub.add_parser("quota")
    sub.add_parser("rescan")
    sub.add_parser("shutdown")

    p_rec = sub.add_parser("record")
    p_rec.add_argument("action", choices=["start", "stop"])
    p_rec.add_argument("--tag", default="")

    p_dump = sub.add_parser("dump")
    p_dump.add_argument("--last", type=float, default=30.0)
    p_dump.add_argument("--tag", default="倒带")

    p_keep = sub.add_parser("keep")
    p_keep.add_argument("dir")
    p_keep.add_argument("--unkeep", action="store_true")

    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2

    if args.cmd == "record":
        resp = call("record." + args.action, socket_path=args.socket, tag=args.tag)
    elif args.cmd == "dump":
        resp = call("dump", socket_path=args.socket, seconds=args.last, tag=args.tag)
    elif args.cmd == "keep":
        resp = call("keep", socket_path=args.socket, dir=args.dir,
                    keep=not args.unkeep)
    else:
        resp = call(args.cmd, socket_path=args.socket)

    print(json.dumps(resp, ensure_ascii=False, indent=2) if args.json else _human(resp))
    return 0 if resp.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
