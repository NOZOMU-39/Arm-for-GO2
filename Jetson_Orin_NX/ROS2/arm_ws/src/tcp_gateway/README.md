# tcp_gateway — 前端(公用) ↔ Jetson 统一入口

Windows 操作界面(公用前端)连 Jetson 的"门卫"：**仿 ESP32 v2.1.3 TCP 协议**，界面现有代码零改动（`wifi_can_client.py` 原样可用，IP 填 Jetson 即可）。一期 v1 帧透传；二期语义化接 arm_controller；三期外设监控接入（视频走独立流，不进本网关）。

## 模块

| 文件 | 干什么 |
|---|---|
| `tcp_gateway/frames.py` | ESP32 v2.1.3 帧协议编解码（纯 Python 零 ROS 依赖，单测覆盖） |
| `tcp_gateway/gateway_node.py` | ROS2 节点：TCP 8888 监听 / 0x04→/arm/can/tx / rx→0x03/0x05 推送 / 命令响应 |
| `test/` | frames 编解码单测（固定字节向量 + socket 往返） |

## 常用入口

```bash
python -m pytest test/ -q          # 本机
tcp_gateway                        # Jetson: 起网关(需 can_bridge 已跑)
# Windows 界面: 连接页"无线"通道 IP 填 Jetson 地址(192.168.31.114) 即连
```

## 注意（v1 期）

- **总线单主 = 界面**：v1 界面自己轮询+安全链；controller 不要起（或 `poll_enable:=false` 只旁听）
- 帧协议细节（封装/批帧/命令码）以 `wifi_can_client.py` 为兼容基准，改动须与它互测
- **读超时 ≠ 断开（2026-09-06 修复）**：客户端静默 >1s 曾被踢下线（界面设零节奏 0x64 后停 1s → 0x76 永远发不出，真机 03:16 事故）——现纯静默超时抛 TimeoutError 上层 continue，仅半帧超时/对端关闭才断开；回归测试 4 条在 `test/test_frames.py`
