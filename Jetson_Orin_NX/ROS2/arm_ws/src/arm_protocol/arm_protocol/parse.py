"""回复解析 parse_reply（移植自 PROTO_CORE JS parseReply，巨型 switch 逐 case 翻译）

签名: parse_reply(proto, can_id, data, motor=None)
  proto: "V3"(V3.9) / "V43"(V4.3,解析用 V44 分支但 0x94 两字节) / "V44"(V4.4)
  can_id: 0x140-0x15F(命令回显)/0x240-0x25F(电机回复)/0x280(广播)/0x300(系统)
  data: bytes 8 字节帧
  motor: 电机配置 dict（键名对齐 JS 注册表对象: gear/dir/E4/v9cSemantics...）；None=无配置(gear=1/dir=1)

返回 dict {motor_id, broadcast, sys300, cmd, summary, values}；无法识别返回 None。
  values 键名与 JS 版完全一致（解析结果数据契约，供上层对照调试）。
  summary 为人读中文摘要（日志用），与 JS 版语义等价、不保证逐字符一致
  （JS 模板字符串含 Number.toString() 裸插值，跨语言格式有浮点尾巴差异，勿作一致性判据）。

已知语义要点（勿凭手册推翻）:
  - V3 的 0x92 多圈角在 D1-D4（JS 注释: 2026-08-20 日志实证, 勿读 D4~7）
  - V4 的 0x92 在 D4-D7（与 V3 不同）
  - V4.3 0x94 = u16(6) 0~359.99; V4.4 0x94 = i32(4) ±180°
  - v9cSemantics 兼容字段: 电机配置带 "angle" 才把 V3 0x9C 的 D6-7 当角度读，
    否则一律按转子相位脉冲(enc)——项目内 X8-PRO 实测为脉冲语义。
"""

from .angles import amp2rot, dir_of, gear_of, rot2out
from .bytes_ops import f32, i16, i32, u16, u32
from .errors import V44_ACC_NAME, V44_FUNC_NAME, V44_MODE, V44_PID_NAME, V3_FUNC_NAME, V3_MODE, err_text


def decode79_reply(data: bytes) -> dict:
    """0x79 读/写 ID 回复解析: 读回复的 D6-D7 是回复 CAN 地址(0x240+编号), 不是电机编号本身"""
    b = data
    if len(b) < 8:
        return {"mode": "invalid", "id": None, "reply_can_id": None,
                "summary": "0x79 回复长度不足,未确认编号"}
    op = b[2]
    if op == 1:
        reply_can_id = u16(b, 6)
        motor_id = reply_can_id - 0x240 if 0x241 <= reply_can_id <= 0x260 else None
        if motor_id is None:
            return {"mode": "read", "id": None, "replyCanId": reply_can_id,
                    "summary": "已收到 0x79 只读回复,回复地址无法换算为合法编号"}
        return {"mode": "read", "id": motor_id, "replyCanId": reply_can_id,
                "summary": f"已收到 0x79 只读回复,编号 {motor_id}"}
    if op == 0:
        motor_id = b[7]
        if 1 <= motor_id <= 32:
            return {"mode": "writeEcho", "id": motor_id, "replyCanId": None,
                    "summary": f"收到 0x79 回显,编号 {motor_id}"}
        return {"mode": "writeEcho", "id": None, "replyCanId": None,
                "summary": "收到 0x79 回显,编号不在 1~32"}
    return {"mode": "unknown", "id": None, "replyCanId": None,
            "summary": "收到 0x79 回复,操作类型无法确认"}


def parse_reply(proto: str, can_id: int, data, motor=None) -> dict | None:
    """解析电机回复帧 → {motor_id, broadcast, sys300, cmd, summary, values}"""
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
        return None
    n = 0
    broadcast = False
    sys300 = False
    if can_id == 0x280:
        broadcast = True
    elif can_id == 0x300:
        sys300 = True
    elif 0x140 <= can_id <= 0x15F:
        n = can_id - 0x140
    elif 0x240 <= can_id <= 0x25F:
        n = can_id - 0x240
    if not n and not broadcast and not sys300:
        return None
    cmd = data[0]
    out = {"motor_id": n, "broadcast": broadcast, "sys300": sys300,
           "cmd": cmd, "summary": "", "values": {}}
    rm = motor  # 电机配置（None → gear=1/dir=1，与 JS selMotor() 无选中一致）

    if proto == "V3":
        if cmd == 0x9A:
            b = data[3]
            if b == 1:
                brake_txt = "已释放"
            elif b == 0:
                brake_txt = "已锁定"
            else:
                brake_txt = f"未定义(0x{b:02X},无抱闸型号属正常)"
            out["values"] = {"temp": data[1], "brake": brake_txt, "brakeRaw": b,
                             "volt": u16(data, 4) / 10, "err": u16(data, 6)}
            volt = out["values"]["volt"]
            volt_txt = "—(旧固件不回传,正常)" if volt == 0 else f"{volt:.1f}V"
            out["summary"] = (f"温度 {out['values']['temp']}℃ · 电压 {volt_txt} · "
                              f"抱闸{out['values']['brake']} · {err_text(out['values']['err'], 'V3')}")
        elif cmd == 0x9C:
            sem = (rm or {}).get("v9cSemantics")
            out["values"] = {"temp": data[1], "iq": i16(data, 2) / 100,
                             "spd": i16(data, 4), "enc": u16(data, 6)}
            if sem == "angle":
                out["values"]["ang"] = i16(data, 6)
                out["values"]["enc"] = None
                out["summary"] = (f"温度 {out['values']['temp']}℃ · 电流 "
                                  f"{amp2rot(out['values']['iq'], rm):.2f}A · "
                                  f"速度 {rot2out(out['values']['spd'], rm)}dps · "
                                  f"角度 {rot2out(out['values']['ang'], rm)}°(0x9C)")
            else:
                out["summary"] = (f"温度 {out['values']['temp']}℃ · 电流 "
                                  f"{amp2rot(out['values']['iq'], rm):.2f}A(输出轴) · "
                                  f"速度 {rot2out(out['values']['spd'], rm):.2f}dps(输出轴) · "
                                  f"编码器 {out['values']['enc']} 脉冲(转子侧原始)")
        elif cmd == 0x9D:
            out["values"] = {"ia": i16(data, 1) / 100, "ib": i16(data, 3) / 100, "ic": i16(data, 5) / 100}
            v = out["values"]
            out["summary"] = (f"相电流 A {v['ia']:.1f}A · B {v['ib']:.1f}A · C {v['ic']:.1f}A")
        elif cmd in (0x30, 0x31, 0x32):
            pid = [data[2], data[3], data[4], data[5], data[6], data[7]]
            out["values"] = {"pid": pid}
            echo = "(回显,写入成功)" if cmd != 0x30 else ""
            out["summary"] = (f"PID 六参数:电流KP {pid[0]} KI {pid[1]} · 速度KP {pid[2]} KI {pid[3]} · "
                              f"位置KP {pid[4]} KI {pid[5]}{echo}")
        elif cmd in (0x42, 0x43):
            idx = data[1]
            out["values"] = {"idx": idx, "acc": i32(data, 4)}
            name = V44_ACC_NAME.get(idx) or ("索引" + str(idx))
            out["summary"] = f"加速度 {name} = {out['values']['acc']} dps/s"
        elif cmd == 0x90:
            out["values"] = {"enc": u16(data, 2), "raw": u16(data, 4), "off": u16(data, 6)}
            out["summary"] = (f"单圈编码器 {out['values']['enc']}"
                              f"(原始 {out['values']['raw']},零偏 {out['values']['off']})脉冲")
        elif cmd == 0x92:
            # ⚠️ V3 的 0x92 int32 角度在 D1-D4 小端(2026-08-20 日志实证,勿读 D4~7)
            _pos = i32(data, 1) / 100 / gear_of(rm) * dir_of(rm)
            out["values"] = {"pos": _pos if _pos != 0 else 0.0}
            mapped = ",方向已映射" if dir_of(rm) == -1 else ""
            out["summary"] = f"多圈角度 {out['values']['pos']:.2f}°(输出轴{mapped})"
        elif cmd == 0x94:
            _pos = u16(data, 6) / 100 / gear_of(rm) * dir_of(rm)
            out["values"] = {"pos": _pos if _pos != 0 else 0.0}
            mapped = ",方向已映射" if dir_of(rm) == -1 else ""
            out["summary"] = f"单圈角度 {out['values']['pos']:.2f}°(输出轴{mapped},0~359.99)"
        elif cmd in (0x60, 0x61, 0x62):
            out["values"] = {"enc": i32(data, 4)}
            out["summary"] = f"编码器 {out['values']['enc'] * dir_of(rm)} 脉冲(方向已映射;原始 {out['values']['enc']})"
        elif cmd == 0x70:
            out["values"] = {"mode": data[7]}
            mode = V3_MODE.get(out["values"]["mode"])
            out["summary"] = f"运行模式 {mode or format(out['values']['mode'], 'x')}"
        elif cmd == 0x71:
            out["values"] = {"power": u16(data, 6) / 10}
            out["summary"] = f"功率 {out['values']['power']:.1f}W"
        elif cmd == 0x79:
            out["values"] = decode79_reply(data)
            out["summary"] = out["values"]["summary"]
        elif cmd == 0xB1:
            out["values"] = {"ms": u32(data, 4)}
            out["summary"] = f"运行时间 {(out['values']['ms'] / 1000):.1f}s"
        elif cmd == 0xB2:
            out["values"] = {"d": u32(data, 4)}
            out["summary"] = f"固件日期 {out['values']['d']}"
        elif cmd == 0xB3:
            out["values"] = {"ms": u32(data, 4)}
            out["summary"] = f"通信中断保护 {out['values']['ms']}ms"
        elif cmd == 0xB4:
            out["values"] = {"idx": data[7]}
            baud = {0: "CAN 500K", 1: "CAN 1M", 2: "RS485 1M(CAN 无效)"}.get(out["values"]["idx"])
            out["summary"] = f"波特率索引 {out['values']['idx']}({baud})"
        elif cmd == 0xB5:
            out["values"] = {"text": "".join(chr(b) for b in data[1:8])}
            out["summary"] = f"型号:{out['values']['text']}"
        elif cmd == 0x20:
            fidx = data[1]
            fval = i32(data, 4)
            out["values"] = {"idx": fidx, "val": fval}
            name = V3_FUNC_NAME.get(fidx) or ("索引" + str(fidx))
            out["summary"] = f"功能控制 {name} = {fval}(回显,写入成功)"
        elif cmd in (0xA1, 0xA2, 0xA4, 0xA6, 0xA8, 0x80, 0x81, 0x77, 0x78):
            out["values"] = {"temp": data[1], "iq": i16(data, 2) / 100,
                             "spd": i16(data, 4), "enc": u16(data, 6)}
            v = out["values"]
            out["summary"] = (f"回复:温度 {v['temp']}℃ · 电流 {amp2rot(v['iq'], rm):.2f}A(输出轴) · "
                              f"速度 {rot2out(v['spd'], rm):.2f}dps(输出轴) · 编码器 {v['enc']}")
        else:
            out["summary"] = "未识别的 V3.x 回复"
    else:
        # V4.3 / V4.4（解析分叉: 0x94 两字节 vs int32）
        if cmd == 0x9A:
            out["values"] = {"temp": data[1], "mosTemp": data[2],
                             "brake": "已解锁" if data[3] else "已锁定",
                             "volt": u16(data, 4) / 10, "err": u16(data, 6)}
            v = out["values"]
            out["summary"] = (f"温度 {v['temp']}℃(MOS {v['mosTemp']}℃) · 电压 {v['volt']:.1f}V · "
                              f"抱闸{v['brake']} · {err_text(v['err'], 'V44')}")
        elif cmd == 0x9C:
            out["values"] = {"temp": data[1], "iq": i16(data, 2) / 100,
                             "spd": i16(data, 4), "ang": i16(data, 6)}
            v = out["values"]
            mapped = ",方向已映射" if dir_of(rm) == -1 else ""
            out["summary"] = (f"温度 {v['temp']}℃ · 电流 {amp2rot(v['iq'], rm):.2f}A · "
                              f"速度 {rot2out(v['spd'], rm):.2f}dps · "
                              f"角度 {rot2out(v['ang'], rm):.2f}°(输出轴{mapped})")
        elif cmd == 0x9D:
            out["values"] = {"ia": i16(data, 1) / 100, "ib": i16(data, 3) / 100, "ic": i16(data, 5) / 100}
            v = out["values"]
            out["summary"] = f"相电流 A {v['ia']:.2f}A · B {v['ib']:.2f}A · C {v['ic']:.2f}A"
        elif cmd == 0x92:
            # ⚠️ V4 的 0x92 int32 在 D4-D7（与 V3 的 D1-D4 不同）
            _pos = i32(data, 4) / 100 * dir_of(rm)
            out["values"] = {"pos": _pos if _pos != 0 else 0.0}
            mapped = ",方向已映射" if dir_of(rm) == -1 else ""
            out["summary"] = f"多圈角度 {out['values']['pos']:.2f}°(输出轴{mapped})"
        elif cmd == 0x94:
            if proto == "V44":
                _pos = i32(data, 4) / 100 * dir_of(rm)
                rng = "±180°"
            else:  # V43 两字节 0~359.99
                _pos = u16(data, 6) / 100 * dir_of(rm)
                rng = "0~359.99"
            out["values"] = {"pos": _pos if _pos != 0 else 0.0}
            mapped = ",方向已映射" if dir_of(rm) == -1 else ""
            out["summary"] = f"单圈角度 {out['values']['pos']:.2f}°(输出轴{mapped},{rng})"
        elif cmd in (0x63, 0x64):
            encoder_offset = i32(data, 4)
            out["values"] = {"encoderOffset": encoder_offset}
            label = "零偏写入回显" if cmd == 0x63 else "当前位置设零回读"
            out["summary"] = f"{label}: {encoder_offset} 脉冲"
        elif cmd in (0x60, 0x61, 0x62):
            encoder_value = i32(data, 4)
            out["values"] = {"enc": encoder_value}
            if cmd == 0x62:
                out["values"]["encoderOffset"] = encoder_value
            label = {0x60: "多圈位置", 0x61: "多圈原始位置", 0x62: "多圈零偏"}[cmd]
            out["summary"] = f"{label}: {encoder_value * dir_of(rm)} 脉冲(原始 {encoder_value})"
        elif cmd in (0x30, 0x31, 0x32):
            idx = data[1]
            _val = f32(data, 4)
            out["values"] = {"idx": idx, "val": _val if _val != 0 else 0.0}
            name = V44_PID_NAME.get(idx) or idx
            out["summary"] = f"PID 索引 {name} = {out['values']['val']:.5f}"
        elif cmd in (0x42, 0x43):
            idx = data[1]
            out["values"] = {"idx": idx, "acc": i32(data, 4)}
            name = V44_ACC_NAME.get(idx) or ("索引" + str(idx))
            out["summary"] = f"加速度 {name} = {out['values']['acc']} dps/s"
        elif cmd == 0x70:
            out["values"] = {"mode": data[7]}
            mode = V44_MODE.get(out["values"]["mode"])
            out["summary"] = f"运行模式 {mode or '未知'}"
        elif cmd == 0xB1:
            out["values"] = {"ms": u32(data, 4)}
            out["summary"] = f"运行时间 {(out['values']['ms'] / 1000):.1f}s"
        elif cmd == 0xB2:
            out["values"] = {"d": u32(data, 4)}
            out["summary"] = f"固件日期 {out['values']['d']}"
        elif cmd == 0xB3:
            out["values"] = {"ms": u32(data, 4)}
            out["summary"] = f"通信中断保护 {out['values']['ms']}ms"
        elif cmd == 0xB4:
            out["values"] = {"idx": data[7]}
            baud = {0: "1M", 1: "500K", 2: "250K"}.get(out["values"]["idx"])
            out["summary"] = f"波特率索引 {out['values']['idx']}({baud})"
        elif cmd == 0xB5:
            part = data[1]
            text = "".join(chr(b) for b in data[2:7])
            out["values"] = {"part": part, "text": text}
            out["summary"] = f"型号片段 {part}:{text}"
        elif cmd == 0xB6:
            out["values"] = {"on": data[7]}
            out["summary"] = f"主动回复:{'已开启' if out['values']['on'] else '已关闭'}"
        elif cmd == 0x79:
            out["values"] = decode79_reply(data)
            out["summary"] = out["values"]["summary"]
        elif cmd == 0x20:
            fidx = data[1]
            fval = i32(data, 4)
            out["values"] = {"idx": fidx, "val": fval}
            name = V44_FUNC_NAME.get(fidx) or ("索引" + str(fidx))
            s = f"功能控制 {name} = {fval}(回显,写入成功)"
            if fidx == 6 or fidx == 7:
                g = gear_of(rm)
                if fval == 65535:
                    s += f";输出轴 {(fval / g):.0f}°(默认值 65535≈未设限,出厂默认)"
                else:
                    s += f";输出轴 {(fval / g):.0f}°"
            out["summary"] = s
        elif cmd in (0x80, 0x81, 0x77, 0x78):
            out["values"] = {"temp": data[1], "iq": i16(data, 2) / 100,
                             "spd": i16(data, 4), "ang": i16(data, 6)}
            v = out["values"]
            out["summary"] = (f"系统回复:温度 {v['temp']}℃ · 电流 {amp2rot(v['iq'], rm):.2f}A · "
                              f"速度 {rot2out(v['spd'], rm):.2f}dps · 角度 {rot2out(v['ang'], rm):.2f}°")
        elif cmd in (0xA1, 0xA2, 0xA4, 0xA8, 0xA9, 0x72, 0x73):
            out["values"] = {"temp": data[1], "iq": i16(data, 2) / 100,
                             "spd": i16(data, 4), "ang": i16(data, 6)}
            v = out["values"]
            out["summary"] = (f"控制回复:温度 {v['temp']}℃ · 电流 {amp2rot(v['iq'], rm):.2f}A · "
                              f"速度 {rot2out(v['spd'], rm):.2f}dps · 角度 {rot2out(v['ang'], rm):.2f}°")
        else:
            out["summary"] = "未识别的 V4.4 回复"
    return out
