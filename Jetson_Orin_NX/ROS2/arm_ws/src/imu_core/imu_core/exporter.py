# -*- coding: utf-8 -*-
"""导出：定长 bin -> CSV / JSONL，并做回放自检。

CSV 列固定为 record.CSV_COLUMNS；t_rel_s 以该路首条记录的 t_rx_ns 为零点。
不用 numpy / pandas：Jetson 上 stdlib 就够，别人拿成品也不缺依赖。
"""
import json
import os

from .record import CSV_COLUMNS, RECORD_SIZE, load_meta, read_stream


def _fmt(v):
    if isinstance(v, float):
        return "%.9g" % v
    return str(v)


def export_csv(dirpath, role, out_path, meta=None):
    meta = meta or load_meta(dirpath)
    n = 0
    t0 = None
    with open(out_path, "w", encoding="utf-8", newline="") as out:
        out.write(",".join(CSV_COLUMNS) + "\n")
        for rec in read_stream(dirpath, role, meta=meta):
            if t0 is None:
                t0 = rec["t_rx_ns"]
            row = [(rec["t_rx_ns"] - t0) / 1e9]
            row += [rec[k] for k in ("ax", "ay", "az", "gx", "gy", "gz",
                                     "qw", "qx", "qy", "qz")]
            row += [rec["status"], rec["temperature"]]
            out.write(",".join(_fmt(v) for v in row) + "\n")
            n += 1
    return n


def export_jsonl(dirpath, role, out_path, meta=None):
    meta = meta or load_meta(dirpath)
    n = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for rec in read_stream(dirpath, role, meta=meta):
            out.write(json.dumps(rec, sort_keys=True) + "\n")
            n += 1
    return n


def verify(dirpath, role, meta=None, sample_checked=None):
    """回放自检：检查文件长度是 64 的整数倍、meta 记的帧数与实际一致、可选抽样校验字段。

    返回 dict(ok, frames, meta_frames, bytes, problems[sample 不符条数])。
    """
    meta = meta or load_meta(dirpath)
    info = (meta.get("streams") or {}).get(role) or {}
    name = info.get("file") or (role + ".bin")
    path = os.path.join(dirpath, name)
    size = os.path.getsize(path)
    problems = []
    if size % RECORD_SIZE != 0:
        problems.append("文件长度 %d 不是 %d 的整数倍（末尾半条记录）" % (size, RECORD_SIZE))
    frames = size // RECORD_SIZE
    meta_frames = info.get("frames")
    if meta_frames is not None and meta_frames != frames:
        problems.append("meta 记 %s 帧，实际 %d 帧" % (meta_frames, frames))
    nbad = 0
    if sample_checked:
        for rec in read_stream(dirpath, role, meta=meta, limit=sample_checked):
            if not (rec["t_rx_ns"] > 0):
                nbad += 1
    return {"ok": not problems, "frames": frames, "meta_frames": meta_frames,
            "bytes": size, "problems": problems, "bad_samples": nbad}
