# -*- coding: utf-8 -*-
"""花名册：UUID -> 岗位（role）。**绑定在配置文件里，不在代码里**。

为什么要这一层（用户 2026-11-06 定）：
  - 换件不该改代码：换了 IMU，只要把新 UUID 写进花名册即可；
  - 认不出来也不许罢工：没有登记的设备照样出数据，只是 role=unassigned + 告警；
  - 厂家没有硬件唯一 ID 时降级为“按 USB 物理端口记名”，日志明写弱身份。

文件格式：JSON（标准库即可解析，不引第三方依赖）。默认 imu_roles.json。
"""
import json
import os
import tempfile
import time
from dataclasses import dataclass, field

from .identity import DeviceIdentity, IDENTITY_UUID

ROLE_MUZZLE = "muzzle"          # 枪口端（随动，装在枪/末端）
ROLE_BASE = "base"              # 基座端（装在 X8 定子侧）
ROLE_UNASSIGNED = "unassigned"  # 未登记 / 判别不出
ROLES = (ROLE_MUZZLE, ROLE_BASE, ROLE_UNASSIGNED)

SCHEMA = 1


class RosterError(Exception):
    pass


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class Assignment:
    """一台设备最终的岗位判定结果。"""

    identity: DeviceIdentity
    role: str
    source: str          # roster / usb_path(weak) / unassigned / discriminated
    weak: bool = False
    note: str = ""


class Roster:
    """UUID/端口 -> role 的映射，可从/向 JSON 读写。"""

    def __init__(self, path=None, data=None):
        self.path = path
        self.data = data if data is not None else {}
        self.data.setdefault("schema", SCHEMA)
        self.data.setdefault("devices", {})
        self.data.setdefault("usb_path_fallback", {})

    # -- 读写

    @classmethod
    def load(cls, path):
        """读花名册；文件不存在时返回空册（不报错：首次使用就是这样）。"""
        if not os.path.exists(path):
            return cls(path=path)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            raise RosterError("花名册读取失败 %s: %s" % (path, exc))
        if data.get("schema") not in (None, SCHEMA):
            raise RosterError("花名册 schema 不兼容：%r" % (data.get("schema"),))
        return cls(path=path, data=data)

    def save(self):
        """原子写：先写临时文件再 replace，避免写一半把花名册弄坏。"""
        if not self.path:
            raise RosterError("未指定路径，无法保存")
        self.data["updated_utc"] = _now_iso()
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".imu_roles.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    # -- 查

    def resolve(self, identity):
        """返回 (role, source)。查不到就是 unassigned + "unassigned"。"""
        if identity.kind == IDENTITY_UUID:
            rec = self.data["devices"].get(identity.value)
            if rec and rec.get("role") in ROLES:
                return rec["role"], "roster"
        port = identity.usb_path or (identity.value if identity.kind != IDENTITY_UUID else "")
        if port:
            role = self.data["usb_path_fallback"].get(port)
            if role in ROLES:
                return role, "usb_path(weak)"
        return ROLE_UNASSIGNED, "unassigned"

    def entries(self):
        return dict(self.data["devices"])

    # -- 写

    def bind(self, identity, role, label=""):
        """把一台设备绑到岗位。返回旧岗位（没有则 None）。"""
        if role not in ROLES:
            raise RosterError("未知岗位 %r（可选 %s）" % (role, ", ".join(ROLES)))
        if identity.kind != IDENTITY_UUID:
            # 弱身份只能按端口记：日志与文件里都写明，提醒使用者别换插口
            old = self.data["usb_path_fallback"].get(identity.value)
            self.data["usb_path_fallback"][identity.value] = role
            return old
        old = (self.data["devices"].get(identity.value) or {}).get("role")
        self.data["devices"][identity.value] = {
            "role": role,
            "label": label or identity.label,
            "model": identity.model,
            "vendor": identity.vendor,
            "serial": identity.serial,
            "last_seen_utc": _now_iso(),
            "last_usb_path": identity.usb_path,
        }
        return old

    def unbind(self, uuid_value):
        return self.data["devices"].pop(uuid_value, None)

    def touch(self, identity):
        """更新 last_seen / last_usb_path，不改岗位。"""
        if identity.kind != IDENTITY_UUID:
            return
        rec = self.data["devices"].get(identity.value)
        if rec is None:
            return
        rec["last_seen_utc"] = _now_iso()
        rec["last_usb_path"] = identity.usb_path


def resolve_all(identities, roster):
    """对一组身份批量查岗位，返回 Assignment 列表（不写文件）。"""
    out = []
    for ident in identities:
        role, source = roster.resolve(ident)
        out.append(Assignment(identity=ident, role=role, source=source, weak=ident.weak))
    return out
