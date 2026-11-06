# imu_core — IMU 核心层（与厂家无关）

> 给 AI 的接口说明见 `AGENTS.md`（项目根那套约定里，模块文档 AI 只写 AGENTS；本包暂无 AGENTS，接口都在代码 docstring 里）。
> 一句话：**换 IMU 厂家时，只换驱动包，这一包一行不用改。**

## 它管什么

| 模块 | 作用 |
|---|---|
| `identity` | 设备身份：UUID（强）/ USB 端口（弱）/ 未知；弱身份会告警 |
| `roster` | 花名册：UUID → 岗位（muzzle 枪口端 / base 基座端 / unassigned），JSON 文件 |
| `registry` | 枚举 `/dev/ttyUSB*`、查 USB 物理口、批量派岗（含重复岗位告警） |
| `discriminator` | 现场核验：两台都认不出时，按角速度 RMS 判“谁在动”→ 谁是末端 |
| `quality` | 状态位解码（饱和/静止）+ 滚动窗口统计 |
| `types` | 统一样本 `ImuSample`（字段名与单位统一，语义不抽象） |
| `driver` | 驱动抽象基类：问名字 / 要数据 / 按需求配置 |

## 三条铁律

1. **时间戳只有一个基准**：接收端 `CLOCK_MONOTONIC`（`t_rx_ns`）。帧内 `system_time` 是 u32 毫秒、24 h 回绕，**只做丢帧判据，绝不当时间基准**。
2. **认不出来也要出数据**：没有登记的设备 `role=unassigned`，照样输出，只告警。
3. **绝不瞎猜**：动臂判别只给建议，默认不采纳；要么人工 `--bind`，要么显式 `--auto-discriminate`。

## 怎么跑（M1 阶段，不需要 ROS）

```bash
# 单元测试（纯逻辑，任何机器都能跑）
cd src/imu_core && python3 -m unittest discover -s test -t . -v
```

真机识别用驱动包的命令行：见 `../imu_hi12s2/README.md` 的 `imu_identify`。

## 状态

- M1：核心层完成（20 个单测通过）。
- M2 会在这里加 `buffer`（60 s 环形缓冲）与 `recorder`（按需录制 + 配额）。
