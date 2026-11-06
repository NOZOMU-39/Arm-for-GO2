# -*- coding: utf-8 -*-
"""存储配额：超限时删最老的非保护录制目录。

策略（2026-11-06 定，见 03「存储预算」）：
  - 只动 root 下【有 meta.json】的目录（孤儿目录不猜、不删）；
  - 有 KEEP 标记的永不自动删；
  - 正在写（meta.state == "recording"）或最近 min_age_s 内改动的，不删；
  - 删除顺序 = 按创建时间从老到新，删到用量低于 quota 为止。
"""
import os
import shutil
import time

from .record import KEEP_NAME, META_NAME, dir_size, has_meta, is_keep, load_meta


def list_sessions(root):
    """返回 [{path, name, size, created, keep, state}]，按创建时间升序。"""
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isdir(path) or not has_meta(path):
            continue
        try:
            meta = load_meta(path)
        except (OSError, ValueError):
            continue
        out.append({
            "path": path,
            "name": name,
            "size": dir_size(path),
            "created": float(meta.get("created_epoch") or os.path.getmtime(path)),
            "keep": is_keep(path),
            "state": meta.get("state", ""),
            "frames": sum((v.get("frames") or 0) for v in (meta.get("streams") or {}).values()),
        })
    out.sort(key=lambda d: d["created"])
    return out


def usage(root):
    return sum(s["size"] for s in list_sessions(root))


def enforce(root, quota_bytes, now=None, min_age_s=600, protected=()):
    """执行配额。返回被删目录列表（path）。

    protected: 额外保护名单（正在写的目录），元素为绝对路径或目录名。
    """
    now = time.time() if now is None else now
    prot = set()
    for p in protected or ():
        prot.add(p)
        prot.add(os.path.basename(p))
    sessions = list_sessions(root)
    total = sum(s["size"] for s in sessions)
    removed = []
    for s in sessions:                      # 已按 created 升序
        if total <= quota_bytes:
            break
        if s["keep"] or s["state"] == "recording":
            continue
        if now - s["created"] < min_age_s:
            continue
        if s["path"] in prot or s["name"] in prot:
            continue
        shutil.rmtree(s["path"], ignore_errors=True)
        total -= s["size"]
        removed.append(s["path"])
    return removed


def mark_keep(dirpath, keep=True):
    p = os.path.join(dirpath, KEEP_NAME)
    if keep:
        open(p, "a").close()
    elif os.path.exists(p):
        os.remove(p)
    return os.path.exists(p)
