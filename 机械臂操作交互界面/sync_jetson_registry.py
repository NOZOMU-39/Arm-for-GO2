# -*- coding: utf-8 -*-
"""从 Jetson 拉取权威 registry.json 并合并到本界面 机械臂注册表.json —— 2026-09-06

背景: 本界面 registry 与 Jetson controller 权威档案(~/ROS2/arm_ws/config/registry.json)
是两份同构副本。校正工具(rest_calib --apply 改 E4)与界面标定(记上电位置改 restDeg)
各写一端 —— 本脚本做「Jetson → 界面」单向合并, 供校正后同步界面显示。

用法(Windows, 需 OpenSSH + 免密密钥已配):
    python sync_jetson_registry.py                 # 默认 Jetson 192.168.137.247
    python sync_jetson_registry.py --host <IP>     # IP 变了用这个
合并字段: E0/E0Date/E4/limMinDeg/limMaxDeg/limMaxSpd/limMaxIq/defaultPosDeg/
          restDeg/restDegDate/turnDeg (按 id) —— 界面本地 name/note 等保留
安全: 界面 registry 先备份 .bak-sync; 仅当界面未运行或运行中(改文件不影响内存,
      需重启界面生效——脚本会提示)。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

KEY = os.path.expanduser("~/.ssh/id_ed25519_jetson_go2")
REMOTE_REG = "/home/nvidia/ROS2/arm_ws/config/registry.json"
LOCAL_REG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "机械臂注册表.json" if os.path.exists(
                             os.path.join(os.path.dirname(os.path.abspath(__file__)), "机械臂注册表.json"))
                         else "dist/机械臂操作交互界面/机械臂注册表.json")

MERGED_KEYS = ("E0", "E0Date", "E4", "limMinDeg", "limMaxDeg", "limMaxSpd",
               "limMaxIq", "defaultPosDeg", "restDeg", "restDegDate", "turnDeg")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.137.247")
    args = ap.parse_args()

    # 1) 拉 Jetson 权威 registry
    tmp = os.path.join(tempfile.gettempdir(), "jetson_registry.json")
    scp = ["scp", "-i", KEY, "-o", "ConnectTimeout=8",
           f"nvidia@{args.host}:{REMOTE_REG}", tmp]
    print("拉取:", " ".join(scp))
    r = subprocess.run(scp, capture_output=True, text=True)
    if r.returncode != 0:
        print("scp 失败:", r.stderr.strip() or r.stdout.strip())
        sys.exit(1)
    jetson = json.load(open(tmp, encoding="utf-8"))

    # 2) 本地 registry(dev 根目录 或 dist)
    if not os.path.exists(LOCAL_REG):
        print("找不到本地注册表:", LOCAL_REG)
        sys.exit(1)
    local = json.load(open(LOCAL_REG, encoding="utf-8"))
    jmap = {m["id"]: m for m in jetson}

    # 3) 合并 + diff
    changed = []
    for m in local:
        j = jmap.get(m["id"])
        if not j:
            continue
        for k in MERGED_KEYS:
            if k in j and j[k] != m.get(k):
                old = m.get(k)
                m[k] = j[k]
                changed.append((m["id"], k, old, j[k]))
    if not changed:
        print("== 无差异, 两侧一致 ==")
        return

    # 4) 备份 + 写回
    shutil.copy(LOCAL_REG, LOCAL_REG + ".bak-sync")
    json.dump(local, open(LOCAL_REG, "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)
    print(f"== 已合并 {len(changed)} 处 ==")
    for mid, k, old, new in changed:
        print(f"  ID{mid} {k}: {old!r} → {new!r}")
    print("[提示] 界面正在运行则内存不变——重启界面后生效")


if __name__ == "__main__":
    main()
