#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CH340 wedged 恢复工具（hub-first，永远不打芯片）。

背景（2026-11-06 于 Jetson Orin NX 实测）：
  CH340 在 1 kHz 满速收流期间或之后 close()，很高概率进入 wedged 状态：
  /dev/ttyUSB* 节点还在，但 os.open() 直接 EIO；dmesg 出现
      usb 1-3.3.1: failed to send control message: -110
      ch341-uart ttyUSB0: failed to read modem status: -110

【两条最重要的实测结论 —— 这是本文件的设计依据】
  1) 唯一稳定有效的恢复动作是 reset **直系父 HUB**。
     当场拓扑：usb1 -> 1-3(Realtek 0bda:5489) -> 1-3.3(Genesys 05e3:0610)
               -> 1-3.3.1 / 1-3.3.2 (CH340)
     reset 1-3.3 之后两口立刻重新枚举，数秒内可 open。
  2) reset CH340 芯片本身不但无效（ioctl 超时），还会把设备整条打下 USB 总线
     （/dev/ttyUSB* 直接消失），把小问题变成大问题。
     —— 所以本工具**永远不 reset 芯片**，只 reset HUB。

  但设备一旦掉出总线，就没法再从 /dev/ttyUSB* 反查它挂在哪个 HUB 上了。
  因此健康时必须把「口 -> 祖先 HUB 链」缓存到磁盘（save_topology），
  恢复时优先读缓存（L2）。这是 2026-11-06 那次「两颗全掉线」事故的直接教训。

恢复链（逐级上升，成功即停）：
  L1  现有 ttyUSB 的 sysfs 祖先 HUB，由深到浅 reset
  L2  拓扑缓存里记录过的 HUB（设备已掉出总线时唯一的线索）
  L3  现场兜底：子设备全为 CH340 且非空的 HUB，由深到浅
  L4  authorized 0/1 软重置（默认关闭；旧记录：HUB 下授权循环会引发
      clear tt error -71 风暴，曾致桌面崩溃）
  L5  人工（拔插 USB 或重启 Jetson）

注意：wedge 时 os.open("/dev/bus/usb/...") 本身会永久阻塞，
      所以一律 O_NONBLOCK + SIGALRM 超时包住，绝不允许裸 open。

用法（Jetson；reset 需要 root，只读自检不需要）：
    sudo -S python3 ch340_recover.py                 # 恢复，默认期望 2 个口
    sudo -S python3 ch340_recover.py --cache-topology
    python3 ch340_recover.py --check                 # 只自检，不动硬件
"""

import argparse
import fcntl
import json
import os
import re
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hi12_link import list_tty_usb, probe_open, usb_port_of  # noqa: E402

USBDEVFS_RESET = 0x5514
SYS_USB = "/sys/bus/usb/devices"
VID_CH340 = "1a86"
PID_CH340 = "7523"
ROOT_HUB_RE = re.compile(r"^usb\d+$")
DEFAULT_CACHE = os.path.expanduser("~/imu_probe/topology.json")


class _Timeout(Exception):
    pass


def _alarm_handler(_signum, _frame):
    raise _Timeout()


def _read(path):
    try:
        with open(path, "r") as fh:
            return fh.read().strip()
    except OSError:
        return None


def is_ch340(name):
    base = os.path.join(SYS_USB, name)
    return _read(os.path.join(base, "idVendor")) == VID_CH340 and \
        _read(os.path.join(base, "idProduct")) == PID_CH340


def list_ch340():
    out = []
    try:
        names = sorted(os.listdir(SYS_USB))
    except OSError:
        return out
    for name in names:
        if not is_ch340(name):
            continue
        base = os.path.join(SYS_USB, name)
        try:
            busnum = int(_read(os.path.join(base, "busnum")) or 0)
            devnum = int(_read(os.path.join(base, "devnum")) or 0)
        except ValueError:
            busnum = devnum = 0
        out.append({"name": name, "base": base, "busnum": busnum, "devnum": devnum})
    return out


def _children(name):
    try:
        names = os.listdir(SYS_USB)
    except OSError:
        return []
    pat = re.compile(r"^" + re.escape(name) + r"\.\d+$")
    return sorted(n for n in names if pat.match(n))


def _parent_of(name):
    if "." in name:
        return name.rsplit(".", 1)[0]
    if "-" in name:
        return name.split("-", 1)[0]
    return None


def _is_hub(name):
    cls = _read(os.path.join(SYS_USB, name, "bDeviceClass"))
    try:
        return cls is not None and int(cls, 16) == 9
    except ValueError:
        return False


def ancestor_hubs(port_path):
    """由 USB 端口路径（如 1-3.3.1）推出其祖先 HUB，由深到浅：['1-3.3', '1-3']。"""
    out = []
    name = port_path
    for _ in range(6):
        parent = _parent_of(name)
        if parent is None or ROOT_HUB_RE.match(parent):
            break
        if _is_hub(parent):
            out.append(parent)
        name = parent
    return out


def tty_usb_port(dev):
    """把 /dev/ttyUSBn 映射到 USB 端口路径（如 1-3.3.1）。拿不到返回 None。

    【别自己解析】/sys/class/tty/ttyUSB0/device 解析出来的是 "ttyUSB0" 本身，
    真正的端口名在路径里 "1-3.3.1:1.0" 的前一段。直接复用 hi12_link.usb_port_of。
    （踩过：自己写 basename 版，结果 usb=None、hubs=[]，缓存全空。）
    """
    return usb_port_of(dev)


def candidate_hubs(expect):
    """现场兜底：子设备全是 CH340 且数量不足 expect 的非空 HUB。"""
    hubs = []
    try:
        names = sorted(os.listdir(SYS_USB))
    except OSError:
        return hubs
    for name in names:
        if ROOT_HUB_RE.match(name):
            continue
        if not _is_hub(name):
            continue
        kids = _children(name)
        # 【坑】空 HUB 会让 all([]) 恒真，从而被误选。
        # 已踩：真凶 1-3.3 因当时 1-3.3.1 已从 sysfs 消失而没被选中，
        # 反而 reset 了总线上毫无关系的 2-1.3，白折腾一轮。
        if not kids:
            continue
        if len(kids) >= expect:
            continue
        if all(is_ch340(k) for k in kids):
            hubs.append(name)
    return hubs


# ---------------------------------------------------------------- 拓扑缓存

def save_topology(path=None, ports=None, verbose=True):
    """把当前「口 -> 祖先 HUB 链」写入缓存。设备健康时调用。"""
    path = path or DEFAULT_CACHE
    ports = ports if ports is not None else list_tty_usb()
    data = {"saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "hubs": [], "ports": {}}
    seen = []
    for p in ports:
        pp = tty_usb_port(p)
        if not pp:
            continue
        hubs = ancestor_hubs(pp)
        data["ports"][p] = {"usb_port": pp, "hubs": hubs}
        for h in hubs:
            if h not in seen:
                seen.append(h)
    data["hubs"] = seen
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except OSError as exc:
        if verbose:
            print("  !! 写拓扑缓存失败: %s" % exc)
        return None
    if verbose:
        print("  [cache] %d 个口 -> HUB %s（%s）" % (len(data["ports"]), seen, path))
    return data


def load_topology(path=None):
    path = path or DEFAULT_CACHE
    try:
        with open(path, "r") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- 硬件动作

def usb_reset(name, base, timeout=3.0):
    """对某 USB 设备做 USBDEVFS_RESET。open 与 ioctl 都带超时。

    注意：这里只应传 HUB。传 CH340 芯片会把它打下总线（见文件头结论 2）。
    """
    busnum = _read(os.path.join(base, "busnum"))
    devnum = _read(os.path.join(base, "devnum"))
    try:
        busnum = int(busnum or 0)
        devnum = int(devnum or 0)
    except ValueError:
        busnum = devnum = 0
    if not busnum or not devnum:
        return False, "%s: 总线上没有有效地址（busnum/devnum=%s/%s），跳过" % (
            name, busnum, devnum)
    devnode = "/dev/bus/usb/%03d/%03d" % (busnum, devnum)

    signal.signal(signal.SIGALRM, _alarm_handler)
    fd = None
    try:
        signal.setitimer(signal.ITIMER_REAL, timeout)
        try:
            fd = os.open(devnode, os.O_WRONLY | os.O_NONBLOCK)
            fcntl.ioctl(fd, USBDEVFS_RESET, 0)
        except _Timeout:
            return False, "%s: reset 超时（open/ioctl 卡住 %.1fs）" % (name, timeout)
        except OSError as exc:
            return False, "%s: reset 失败 %s" % (name, exc)
        finally:
            # 【必须在这里取消】否则定时器会在下面 except 处理期间到点，
            # 二次抛 _Timeout 把整个脚本掀翻（踩过：During handling of the
            # above exception, another exception occurred）。
            signal.setitimer(signal.ITIMER_REAL, 0)
        return True, "%s: reset ok (%s)" % (name, devnode)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def toggle_authorized(name, base):
    path = os.path.join(base, "authorized")
    try:
        with open(path, "w") as fh:
            fh.write("0")
        time.sleep(1.0)
        with open(path, "w") as fh:
            fh.write("1")
    except OSError as exc:
        return False, "%s: authorized 切换失败 %s" % (name, exc)
    return True, "%s: authorized 0/1 完成" % name


def ch341_bound(port_name):
    """该 USB 端口上是否已绑定 ch341 驱动（纯 sysfs 读取，不碰设备）。"""
    return bool(port_name) and os.path.exists(
        os.path.join(SYS_USB, port_name, "driver"))


def attached_ports():
    """当前 ch341 已绑定的串口。纯 sysfs，不做任何 open。"""
    return [p for p in list_tty_usb() if ch341_bound(tty_usb_port(p))]


def wait_ports(expect, timeout=5.0, log=None):
    """等 expect 个口重新挂上 ch341 驱动。返回 (ok, ports, bad)。

    【绝对不要在恢复流程里 open 设备来"验证"】
    CH340 的 wedge 恰恰是被 open/close 触发的：恢复完只要 probe 一下，
    刚救回来的口立刻又被自己打死。2026-11-06 实测：
        reset 1-3.3 成功 -> wait_ports 逐一 probe_open 全 OK
        -> 紧接着 baseline_run 第一次 open 就 EIO
    所以这里只看 sysfs 的驱动绑定状态。真正能不能用，交给消费者进程的
    第一次 open 去证明；恢复工具本身必须做到"零 open"。
    """
    deadline = time.monotonic() + timeout
    while True:
        ports = attached_ports()
        bad = [(q, "ch341 未绑定") for q in list_tty_usb() if q not in ports]
        if len(ports) >= expect:
            return True, ports, bad
        if time.monotonic() >= deadline:
            return False, ports, bad
        time.sleep(0.5)


# ---------------------------------------------------------------- 主流程

def recover(expect=2, allow_authorized=False, cache=None, verbose=True, timeout=3.0):
    """执行 hub-first 恢复。返回 (ok, log_lines, ports)。"""
    log = []

    def say(msg):
        log.append(msg)
        if verbose:
            print(msg)
            sys.stdout.flush()

    ok, ports, bad = wait_ports(expect, timeout=2.0, log=log)
    say("恢复前：%d 个 ttyUSB，ch341 已绑定 %d 个；目标 %d 个"
        % (len(ports) + len(bad), len(ports), expect))
    for q, detail in bad:
        say("  未就绪 %s: %s" % (q, detail))
    if not list_tty_usb():
        say("  !! 总线上一个 ttyUSB 都没有 —— 设备已掉出 USB，只能靠 HUB 恢复")
    # 【为什么不在这里提前返回】
    # ch341 绑定状态无法区分"健康"与"wedge"——楔死的口照样显示已绑定。
    # 唯一可靠的判据是 open 一次，可 open/close 本身又会触发 wedge。
    # 所以 recover() 一律执行 HUB reset：它廉价、可重复、幂等，
    # 而误判"健康"会让调用方带着楔死的口去跑，白白浪费时间。

    if os.geteuid() != 0:
        say("!! reset 需要 root（/dev/bus/usb/* 只对 root 可写）。请用 sudo 运行。")
        return False, log, list_tty_usb()

    def try_hubs(names, tag):
        """按给定顺序逐个 reset HUB，每 reset 一个就复查一次。"""
        for name in names:
            base = os.path.join(SYS_USB, name)
            if not os.path.isdir(base):
                say("  %s: 不存在，跳过" % name)
                continue
            okr, msg = usb_reset(name, base, timeout=timeout)
            say("  " + msg)
            if not okr:
                continue
            time.sleep(1.0)
            ok2, ports2, _ = wait_ports(expect, timeout=8.0)
            if ok2:
                say("%s 成功：%d 个口恢复（reset 了 %s）" % (tag, len(ports2), name))
                save_topology(cache, ports2, verbose=False)
                return True, ports2
        return False, None

    # ---- L1：现有口的祖先 HUB，由深到浅
    l1 = []
    for p in [x for x in ports] + [x for x, _ in bad]:
        pp = tty_usb_port(p)
        for h in (ancestor_hubs(pp) if pp else []):
            if h not in l1:
                l1.append(h)
    l1.sort(key=lambda n: (-n.count("."), n))
    say("L1 候选（现有口的祖先 HUB，由深到浅）：%s" % l1)
    ok, p2 = try_hubs(l1, "L1")
    if ok:
        return True, log, p2

    # ---- L2：拓扑缓存（设备掉出总线后的唯一线索）
    topo = load_topology(cache)
    l2 = []
    if topo:
        for h in topo.get("hubs") or []:
            if h not in l2:
                l2.append(h)
        say("L2 拓扑缓存 %s（保存于 %s）：%s" % (
            cache, topo.get("saved_at", "?"), l2))
    else:
        say("L2 无拓扑缓存（%s）" % (cache,))
    ok, p2 = try_hubs(l2, "L2")
    if ok:
        return True, log, p2

    # ---- L3：现场兜底
    l3 = candidate_hubs(expect)
    l3.sort(key=lambda n: (-n.count("."), n))
    say("L3 现场兜底（子设备全为 CH340 且非空）：%s" % l3)
    ok, p2 = try_hubs(l3, "L3")
    if ok:
        return True, log, p2

    # ---- L4：authorized 软重置（默认关闭）
    if not allow_authorized:
        say("L4 已跳过（需要 --allow-authorized；历史记录：HUB 下授权循环会引发 "
            "clear tt error -71 风暴，曾致桌面崩溃）")
    else:
        targets = [n for n in (l1 + l2 + l3) if os.path.isdir(os.path.join(SYS_USB, n))]
        say("L4 对 %s 做 authorized 0/1" % targets)
        for name in targets:
            okr, msg = toggle_authorized(name, os.path.join(SYS_USB, name))
            say("  " + msg)
            time.sleep(1.0)
        ok, ports2, _ = wait_ports(expect, timeout=15.0)
        if ok:
            say("L4 成功：%d 个口恢复" % len(ports2))
            save_topology(cache, ports2, verbose=False)
            return True, log, ports2

    say("!! 恢复失败。请人工介入：拔插 USB（或换口）／重启 Jetson。")
    for q in list_tty_usb():
        say("  残留口 %s: ch341 %s" % (
            q, "已绑定" if ch341_bound(tty_usb_port(q)) else "未绑定"))
    return False, log, list_tty_usb()


def main(argv=None):
    ap = argparse.ArgumentParser(description="CH340 wedged 恢复（hub-first）")
    ap.add_argument("--expect", type=int, default=2, help="期望的串口数量（默认 2）")
    ap.add_argument("--allow-authorized", action="store_true",
                    help="允许 L4 authorized 软重置（默认关闭）")
    ap.add_argument("--cache", default=DEFAULT_CACHE, help="拓扑缓存文件路径")
    ap.add_argument("--timeout", type=float, default=3.0, help="单次 reset 超时（秒）")
    ap.add_argument("--check", action="store_true", help="只自检，不动硬件")
    ap.add_argument("--probe", action="store_true",
                    help="自检时额外 open 一次（会触发 wedge，仅调试用）")
    ap.add_argument("--cache-topology", action="store_true",
                    help="只把当前拓扑写入缓存，不动硬件")
    args = ap.parse_args(argv)

    if args.check:
        ports = list_tty_usb()
        print("发现 %d 个 ttyUSB：%s" % (len(ports), ports))
        for q in ports:
            pp = tty_usb_port(q)
            print("  %s  usb=%s  hubs=%s  ch341=%s" % (
                q, pp, ancestor_hubs(pp) if pp else [],
                "已绑定" if ch341_bound(pp) else "未绑定"))
            if args.probe:
                # 注意：--probe 会 open+close，本身就可能把口打死，仅调试时用
                ok, detail = probe_open(q, timeout=2.0)
                print("     probe: %s" % ("OK" if ok else detail))
        topo = load_topology(args.cache)
        print("拓扑缓存 %s: %s" % (args.cache,
                                 ("有，保存于 %s，HUB=%s" % (topo.get("saved_at"), topo.get("hubs")))
                                 if topo else "无"))
        return 0

    if args.cache_topology:
        return 0 if save_topology(args.cache) else 1

    ok, _log, ports = recover(expect=args.expect,
                              allow_authorized=args.allow_authorized,
                              cache=args.cache, timeout=args.timeout)
    print("-" * 60)
    print("RESULT: %s，可用口 %d 个 %s" % ("OK" if ok else "FAIL", len(ports), ports))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
