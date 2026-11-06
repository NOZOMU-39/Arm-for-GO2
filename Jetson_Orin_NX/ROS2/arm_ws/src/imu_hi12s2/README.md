# imu_hi12s2 — HIPNUC HI12S2-MI1-000 驱动（UART / 0x91）

> 一句话：**只负责和这台设备说话**，身份/花名册/时间戳契约在 `imu_core`，这里不重复。

## 它管什么

| 模块 | 作用 |
|---|---|
| `protocol` | 0x91 帧：CRC-16/XMODEM、切帧（含伪帧头保护）、解析；**纯逻辑，可单测** |
| `link` | 串口：裸 `os` + `termios`（Jetson 没有 pyserial），**lflag 全清**，静音/恢复，带硬截止的 ASCII 命令 |
| `driver` | `Hi12s2Driver`：实现 `imu_core.ImuDriver`，输出 `ImuSample` |
| `identify_cli` | 命令行 `imu_identify`：认设备、派岗位、动臂判别、写花名册 |

## 现场用法（不需要 ROS，M1 阶段）

```bash
cd ~/ROS2/arm_ws/src
export PYTHONPATH=$PWD/imu_core:$PWD/imu_hi12s2

# 1) 扫一遍：谁在哪个口、UUID 是多少、当前岗位
python3 -m imu_hi12s2.identify_cli

# 2) 采 6 秒并给动臂判别建议（动一下机械臂再跑，否则两台都太静，它会拒判）
python3 -m imu_hi12s2.identify_cli --listen 6

# 3) 判别结果认可后，固化到花名册（之后插到任何口都认得出）
python3 -m imu_hi12s2.identify_cli --bind uuid:24B4EB573C480701=muzzle
python3 -m imu_hi12s2.identify_cli --bind uuid:243173AE3CCD8701=base

# 4) 机器可读
python3 -m imu_hi12s2.identify_cli --listen 6 --json
```

花名册默认 `~/.config/imu/imu_roles.json`，可用 `--roster` 指定。

## 安全说明（重要）

- 本工具**不改设备配置**（不写波特率、不改输出周期），唯一写操作是你显式 `--bind` 时写花名册。
- 识别时会 `LOG HI91 ONTIME 0` 静音设备；这是运行时命令，重启回默认。采集时由驱动自己开流。
- **open/close 本身会触发 CH340 wedged**（实测：本次 M1 真机第一次跑就两个口全 EIO）。恢复：
  ```bash
  cd ~/imu_probe/baseline && echo 1 | sudo -S python3 -u ch340_recover.py
  ```
  hub-first、零 open、禁 reset 芯片——这是唯一有效路径（详见 IMU AGENTS §2.7）。

## 已实测（2026-11-06，Jetson Orin NX）

```
ttyUSB0  1-3.3.1  uuid:24B4EB573C480701  921600  6000 fps/6s  rms 0.099 dps
ttyUSB1  1-3.3.2  uuid:243173AE3CCD8701  921600  6050 fps/6s  rms 0.040 dps
→ 两台都认出来（UUID 随机走、不随插口）；臂静止时比值 2.5× < 4，discriminator 正确拒判
```

## 状态

- M1：协议层 9 个单测通过；真机识别 + 并行收流通过。
- 待做：角色绑定（需要确认哪台在臂上）、换插口/单插/全拔重插的场景验证。
