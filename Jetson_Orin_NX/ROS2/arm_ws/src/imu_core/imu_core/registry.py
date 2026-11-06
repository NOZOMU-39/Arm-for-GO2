# -*- coding: utf-8 -*-
"""设备枚举与岗位分派：本机 tty 设备 -> 身份 -> 岗位。

这一层回答的是用户最早那个问题——“任意插用什么方法能确定它俩谁是谁”：
    枚举 tty -> 打开问 LOG VERSION 拿 UUID -> 查花名册 -> 得到角色；
    ttyUSB 编号与 USB 口都不参与身份判定，只在没 UUID 时降级为弱身份。

注意：本模块只做“认出来并派岗”，不做持续采集（采集循环在 M2 的 collector）。
"""
import glob
import os
from dataclasses import dataclass, field

from .discriminator import discriminate
from .identity import DeviceIdentity
from .roster import ROLE_BASE, ROLE_MUZZLE, ROLE_UNASSIGNED, ROLES, Assignment, resolve_all


def _natural_key(path):
    digits = "".join(ch for ch in os.path.basename(path) if ch.isdigit())
    return int(digits) if digits else 0


def enumerate_tty_devices(pattern="/dev/ttyUSB*"):
    """按自然序返回 tty 设备路径。编号会漂，**禁止拿它当身份**。"""
    return sorted(glob.glob(pattern), key=_natural_key)


def usb_path_of(dev):
    """tty 设备所在的 USB 物理端口名，如 "1-3.3.2"；失败返回 None。

    做法：解析 /sys/class/tty/<name>/device 的真实路径，找形如 "1-3.3.2:1.0"
    的那一段（含冒号且首字符是数字），它的前一段就是物理端口名。
    """
    name = os.path.basename(dev)
    try:
        real = os.path.realpath("/sys/class/tty/%s/device" % name)
    except OSError:
        return None
    parts = [p for p in real.split("/") if p]
    for idx, part in enumerate(parts):
        if ":" in part and part[:1].isdigit():
            return parts[idx - 1] if idx else None
    return None


@dataclass
class RoleAssignments:
    """一次派岗的完整结果，含告警与判别建议。"""

    assignments: list = field(default_factory=list)   # [Assignment]
    warnings: list = field(default_factory=list)      # [str]
    proposal: object = None                          # DiscriminatorResult 或 None

    def by_key(self):
        return {a.identity.key: a for a in self.assignments}

    def role_of(self, key):
        found = self.by_key().get(key)
        return found.role if found else ROLE_UNASSIGNED


def assign_roles(identities, roster, stats=None, auto_discriminate=False, min_ratio=4.0,
                 expected_roles=(ROLE_MUZZLE, ROLE_BASE)):
    """把一组身份派到岗位上，返回 RoleAssignments（不写花名册）。

    规则（用户 2026-11-06 定）：
      1. 花名册优先；查不到 -> unassigned，**照样出数据**，只告警；
      2. 弱身份（无 UUID）必须告警“勿随意换插口”；
      3. 动臂判别只给**建议**，默认不采纳（auto_discriminate=False），
         因为“绝不瞎猜”——要采纳由调用方显式打开。
    """
    assignments = resolve_all(identities, roster)
    warnings = []

    for item in assignments:
        if item.weak:
            warnings.append(
                "%s 是弱身份（无硬件 UUID），按 USB 端口记名；换插口会认错，勿随意插拔。"
                % item.identity.key
            )
        if item.role == ROLE_UNASSIGNED:
            warnings.append(
                "%s 未登记（role=unassigned）：数据照常输出，但下游需自行决定是否采用。"
                % item.identity.key
            )

    # 同一岗位被两台同时占用 -> 一定是花名册或端口兜底配错了
    used = {}
    for item in assignments:
        if item.role in ROLES and item.role != ROLE_UNASSIGNED:
            used.setdefault(item.role, []).append(item.identity.key)
    for role, keys in used.items():
        if len(keys) > 1:
            warnings.append("岗位 %s 被多台设备占用：%s（花名册需要修正）" % (role, ", ".join(keys)))

    proposal = None
    unresolved = [a.identity.key for a in assignments if a.role == ROLE_UNASSIGNED]
    if stats and len(unresolved) >= 2:
        proposal = discriminate(stats, min_ratio=min_ratio)
        if proposal.ok and auto_discriminate:
            for item in assignments:
                if item.identity.key in proposal.roles:
                    item.role = proposal.roles[item.identity.key]
                    item.source = "discriminated"
            warnings.append("已按动臂判别自动派岗（confidence=%.2f），建议随后固化到花名册。"
                            % proposal.confidence)
        elif proposal.ok:
            warnings.append(
                "动臂判别建议：%s -> muzzle（ratio=%s）；未采纳，需人工 --bind 或 --auto-discriminate。"
                % (max(proposal.ratios, key=proposal.ratios.get),
                   ", ".join("%s=%.2f" % (k, v) for k, v in sorted(proposal.ratios.items())))
            )
        else:
            warnings.append("动臂判别未成功（%s）：请让机械臂动一下再试，或直接查花名册。"
                            % proposal.reason)

    # 岗位缺员：只插了一台、或线/供电有问题时，另一路会静默缺席——必须说出来。
    # 判定前提是“花名册已经认出了至少一台”，否则空花名册首次部署时会一直误报。
    known = [a for a in assignments if a.role != ROLE_UNASSIGNED]
    if known:
        present = set(a.role for a in known)
        for role in expected_roles:
            if role not in present:
                warnings.append(
                    "岗位 %s 的设备不在线（本次只认出 %d 台）：这一路会缺数据，查 USB 与供电。"
                    % (role, len(known))
                )

    return RoleAssignments(assignments=assignments, warnings=warnings, proposal=proposal)
