# -*- coding: utf-8 -*-
"""常驻采集进程（M2）：一次 open、永不 close；内存环形缓冲 + 按需录制 + 配额。

设计要点（都是踩过坑换来的，改之前先看 IMU AGENTS §2.7 与 03「数据契约」）：
  1. **单线程 select 循环**：两路共用一个 reader 线程（P0 基线就是这么跑到 1000 fps x2 的）。
     早先「每路一个线程 + 每帧建 dict/dataclass」实测掉到 937 fps（sys_time 每 ~15 帧缺一帧），
     所以数据面走 driver.read_records() 快路径：一次 struct.unpack 直接产出 64 B 记录。
  2. **只 open 一次**：CH340 楔死的主要触发条件是「满速收流后 close」，本进程不做 close。
  3. **默认不录**：只滚动保留最近 ring_seconds 秒到内存（60 s ≈ 7.7 MB 双路）。
  4. **一路挂了另一路照跑**：读失败只把该路标 DOWN 并后台重连，绝不让一台掉线拖死全进程。

控制接口是 Unix socket 上的一行 JSON（请求一行、应答一行），CLI 见 ctl.py。
"""
import glob
import json
import os
import select
import socket
import threading
import time
import traceback

from imu_core import quota as quota_mod
from imu_core import record as record_mod
from imu_core.registry import assign_roles
from imu_core.ring import MultiRing
from imu_core.roster import Roster, ROLE_UNASSIGNED

from .driver import Hi12s2Driver

DEFAULTS = {
    "dev_glob": "/dev/ttyUSB*",
    "baud": 921600,
    "rate_hz": 1000,
    "ring_seconds": 60,
    "root": "~/imu_data",
    "socket": "~/.local/share/imu/ctl.sock",
    "roster": "~/.config/imu/imu_roles.json",
    "quota_gb": 2.0,
    "min_age_s": 600,
    "select_timeout": 0.5,
    "reconnect_s": 5.0,
}


def _expand(p):
    return os.path.expanduser(p)


def load_config(path=None):
    cfg = dict(DEFAULTS)
    path = path or _expand("~/.config/imu/daemon.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except FileNotFoundError:
        pass
    except ValueError as exc:
        print("[warn] 配置文件 %s 解析失败，用默认值：%s" % (path, exc))
    for key in ("root", "socket", "roster"):
        cfg[key] = _expand(cfg[key])
    return cfg


class DeviceWorker(object):
    """一路设备的持有者（**不自己开线程**，I/O 由 Daemon 的 select 循环统一驱动）。"""

    def __init__(self, dev, cfg):
        self.dev = dev
        self.cfg = cfg
        self.driver = Hi12s2Driver(dev, baud=cfg["baud"], rate_hz=cfg["rate_hz"])
        self.role = ROLE_UNASSIGNED
        self.identity = None
        self.state = "init"
        self.last_error = ""
        self.frames = 0
        self.reconnects = 0
        self.reconnecting = False

    def open_and_identify(self):
        self.driver.open()
        self.identity = self.driver.identify()
        self.driver.start_stream(self.cfg["rate_hz"])
        self.state = "streaming"
        self.last_error = ""
        return True

    def info(self):
        ident = self.identity
        return {
            "dev": self.dev,
            "role": self.role,
            "state": self.state,
            "identity": ident.key if ident else "",
            "serial": getattr(ident, "serial", "") if ident else "",
            "frames": self.frames,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
            "driver": self.driver.stats(),
        }


class Daemon(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self.root = cfg["root"]
        self.started = time.time()
        self.workers = []
        self.lock = threading.RLock()
        self.ring = MultiRing(max(1, int(cfg["ring_seconds"] * cfg["rate_hz"])))
        self.roster = Roster.load(cfg["roster"])
        self.writer = None
        self.record_info = {}
        self.record_lock = threading.Lock()
        self.quota_removed = []
        self._quota_counter = {}
        self.log_lock = threading.Lock()
        self._stop = threading.Event()
        os.makedirs(self.root, exist_ok=True)
        os.makedirs(os.path.dirname(cfg["socket"]), exist_ok=True)

    # ---- 日志

    def log(self, msg):
        with self.log_lock:
            print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)

    # ---- 设备

    def scan(self):
        return sorted(p for p in glob.glob(self.cfg["dev_glob"]) if os.path.exists(p))

    def start_devices(self):
        for dev in self.scan():
            w = DeviceWorker(dev, self.cfg)
            try:
                w.open_and_identify()
                self.workers.append(w)
                self.log("已打开 %s -> %s" % (dev, w.identity.key if w.identity else "?"))
            except (OSError, IOError) as exc:
                self.log("打不开 %s（%s）：%s；跳过（恢复工具：ch340_recover.py）"
                         % (dev, type(exc).__name__, exc))
        self.refresh_roles()

    def refresh_roles(self):
        idents = [w.identity for w in self.workers if w.identity is not None]
        if not idents:
            return None
        result = assign_roles(idents, self.roster)
        by_key = {a.identity.key: a for a in result.assignments}
        for w in self.workers:
            if w.identity is None:
                continue
            a = by_key.get(w.identity.key)
            w.role = a.role if a else ROLE_UNASSIGNED
            self.ring.ensure(w.role)
        for msg in result.warnings:
            self.log("WARN " + msg)
        for w in self.workers:
            self.log("岗位 %s <- %s" % (w.role, w.dev))
        return result

    def reconnect_loop(self, w):
        """后台重连一路设备；成功后把它交回 select 循环。"""
        while not self._stop.is_set():
            time.sleep(self.cfg["reconnect_s"])
            try:
                w.driver = Hi12s2Driver(w.dev, baud=self.cfg["baud"], rate_hz=self.cfg["rate_hz"])
                w.open_and_identify()
                w.reconnects += 1
                w.reconnecting = False
                self.log("设备 %s 已重连（第 %d 次）" % (w.dev, w.reconnects))
                self.refresh_roles()
                return
            except (OSError, IOError) as exc:
                w.last_error = "%s: %s" % (type(exc).__name__, exc)
        w.reconnecting = False

    # ---- 数据面

    def ingest(self, role, blob, t_ns):
        self.ring.append(role, t_ns, blob)
        cnt = self._quota_counter.get(role, 0) + 1
        self._quota_counter[role] = cnt
        if cnt % 60000 == 0 and self.cfg["quota_gb"]:
            self.maybe_quota()
        with self.record_lock:
            if self.writer is not None:
                self.writer.append_blob(role, blob, t_ns)

    def reader_loop(self):
        self.log("采集循环启动（select 单线程）")
        while not self._stop.is_set():
            fds = {}
            for w in list(self.workers):
                if w.state == "streaming":
                    fds[w.driver.link.fd] = w
            if not fds:
                time.sleep(0.5)
                continue
            try:
                ready, _, _ = select.select(list(fds), [], [], self.cfg["select_timeout"])
            except OSError as exc:
                self.log("select 异常：%s" % exc)
                time.sleep(0.5)
                continue
            for fd in ready:
                w = fds.get(fd)
                if w is None:
                    continue
                try:
                    recs = w.driver.read_records()
                except (OSError, IOError) as exc:
                    w.state = "down"
                    w.last_error = "%s: %s" % (type(exc).__name__, exc)
                    self.log("设备 %s 读失败（%s），后台重连；恢复不了就手动跑 "
                             "ch340_recover.py" % (w.dev, w.last_error))
                    if not w.reconnecting:
                        w.reconnecting = True
                        threading.Thread(target=self.reconnect_loop, args=(w,),
                                         daemon=True, name="reconnect-%s" % w.dev).start()
                    continue
                except Exception as exc:
                    w.last_error = "%s: %s" % (type(exc).__name__, exc)
                    self.log("设备 %s 解析异常：%s" % (w.dev, w.last_error))
                    traceback.print_exc()
                    continue
                w.frames += len(recs)
                for _seq, blob, t_ns in recs:
                    self.ingest(w.role, blob, t_ns)

    # ---- 录制

    def record_start(self, tag=""):
        with self.record_lock:
            if self.writer is not None:
                return {"ok": False, "error": "已在录制：%s" % self.writer.dir}
            streams = {}
            for w in self.workers:
                streams[w.role] = {"device": w.identity.key if w.identity else w.dev}
            self.writer = record_mod.SessionWriter(
                self.root, tag=tag, streams=streams,
                config={"baud": self.cfg["baud"], "rate_hz": self.cfg["rate_hz"],
                        "devices": [w.info() for w in self.workers]},
            )
            self.record_info = {"dir": self.writer.dir, "tag": tag,
                                "started_utc": self.writer.meta.get("created_utc")}
            self.log("开始录制 -> %s" % self.writer.dir)
            return {"ok": True, **self.record_info}

    def record_stop(self):
        with self.record_lock:
            if self.writer is None:
                return {"ok": False, "error": "当前没有录制"}
            meta = self.writer.close()
            path = self.writer.dir
            self.writer = None
            self.record_info = {}
            self.log("停止录制 -> %s" % path)
            return {"ok": True, "dir": path, "streams": meta.get("streams")}

    def dump(self, seconds=30, tag="倒带"):
        """把环形缓冲里最近 seconds 秒写成新目录（要求当前没有录制，避免双写交叉）。"""
        with self.record_lock:
            if self.writer is not None:
                return {"ok": False, "error": "正在录制中；先 record stop 再 dump"}
            streams = {}
            for w in self.workers:
                streams[w.role] = {"device": w.identity.key if w.identity else w.dev}
            w = record_mod.SessionWriter(self.root, tag=tag, streams=streams,
                                         config={"source": "ring_dump",
                                                 "seconds": seconds})
            counts = {}
            for role in list(self.ring.roles):
                items = self.ring.last(role, seconds=seconds)
                counts[role] = len(items)
                for t_ns, blob in items:
                    w.append_blob(role, blob, t_ns)
            meta = w.close()
        return {"ok": True, "dir": w.dir, "seconds": seconds, "frames": counts,
                "streams": meta.get("streams")}

    # ---- 配额

    def maybe_quota(self):
        gb = float(self.cfg["quota_gb"] or 0)
        if gb <= 0:
            return []
        protected = [self.writer.dir] if self.writer is not None else []
        removed = quota_mod.enforce(self.root, int(gb * (1024 ** 3)),
                                    min_age_s=self.cfg["min_age_s"], protected=protected)
        if removed:
            self.quota_removed.extend(removed)
            self.log("配额触发，删除 %d 个旧目录：%s" % (len(removed), removed))
        return removed

    # ---- 状态

    def status(self):
        with self.record_lock:
            recording = self.writer is not None
            record = dict(self.record_info)
        return {
            "ok": True,
            "pid": os.getpid(),
            "uptime_s": round(time.time() - self.started, 1),
            "root": self.root,
            "recording": recording,
            "record": record,
            "devices": [w.info() for w in self.workers],
            "ring": self.ring.stats(),
            "usage_bytes": quota_mod.usage(self.root),
            "quota_gb": self.cfg["quota_gb"],
            "quota_removed": len(self.quota_removed),
        }

    # ---- 控制 socket

    def handle(self, req):
        cmd = (req.get("cmd") or "").strip()
        if cmd == "status":
            return self.status()
        if cmd == "record.start":
            return self.record_start(tag=req.get("tag") or "")
        if cmd == "record.stop":
            return self.record_stop()
        if cmd == "dump":
            return self.dump(seconds=float(req.get("seconds") or 30),
                             tag=req.get("tag") or "倒带")
        if cmd == "sessions":
            return {"ok": True, "sessions": quota_mod.list_sessions(self.root)}
        if cmd == "keep":
            path = req.get("dir") or ""
            target = path if os.path.isabs(path) else os.path.join(self.root, path)
            if not os.path.isdir(target):
                return {"ok": False, "error": "目录不存在：%s" % target}
            keep = bool(req.get("keep", True))
            quota_mod.mark_keep(target, keep)
            return {"ok": True, "dir": target, "keep": keep}
        if cmd == "quota":
            return {"ok": True, "removed": self.maybe_quota()}
        if cmd == "rescan":
            self.refresh_roles()
            return {"ok": True, "devices": [w.info() for w in self.workers]}
        if cmd == "shutdown":
            return {"ok": True, "bye": True}
        return {"ok": False, "error": "未知命令：%s" % cmd}

    def serve(self):
        threading.Thread(target=self.reader_loop, daemon=True, name="reader").start()
        path = self.cfg["socket"]
        try:
            os.unlink(path)
        except OSError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.listen(8)
        self.log("控制 socket：%s" % path)
        while True:
            conn, _ = srv.accept()
            try:
                with conn:
                    fh = conn.makefile("rwb")
                    line = fh.readline()
                    if not line:
                        continue
                    try:
                        req = json.loads(line.decode("utf-8"))
                    except ValueError:
                        resp = {"ok": False, "error": "请求不是合法 JSON"}
                    else:
                        try:
                            resp = self.handle(req)
                        except Exception as exc:
                            resp = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
                    fh.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                    fh.flush()
                    if resp.get("bye"):
                        self.log("收到 shutdown，退出")
                        os._exit(0)
            except (BrokenPipeError, ConnectionResetError):
                continue


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="IMU 常驻采集（M2）")
    ap.add_argument("--config", default=None)
    ap.add_argument("--root", default=None)
    ap.add_argument("--socket", default=None)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    if args.root:
        cfg["root"] = _expand(args.root)
    if args.socket:
        cfg["socket"] = _expand(args.socket)

    d = Daemon(cfg)
    d.log("启动：root=%s baud=%d rate=%dHz ring=%ss quota=%.1fGB"
          % (cfg["root"], cfg["baud"], cfg["rate_hz"], cfg["ring_seconds"], cfg["quota_gb"]))
    d.start_devices()
    if not d.workers:
        d.log("一台设备都没打开：先跑 ch340_recover.py，再重启本进程")
    try:
        d.serve()
    except KeyboardInterrupt:
        d.log("收到 Ctrl-C，退出（注意：正常退出会 close 串口，可能触发 CH340 楔死）")


if __name__ == "__main__":
    main()
