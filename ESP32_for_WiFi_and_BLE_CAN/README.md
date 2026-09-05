# ESP32 无线 CAN 通信模块 — 项目目录

> 对微雪 Waveshare ESP32-S3-RS485-CAN 无线通信模块的开发项目集合。

---

# 📖 第一部分：这是什么

| 工程 | 说明 | 状态 |
|------|------|------|
| `ESP32 for WiFi CAN Custom\` | **WiFi 版（主力）**：TCP/HTTP 无线 CAN 中继，三级通道自动降级（STA 热点→AP→USB 串口），批帧/UDP 高吞吐（3~5k+ 帧/s） | ✅ 在用 |
| `ESP32 for BLE CAN Custom\` | **蓝牙版**：BLE 无线 CAN 中继 | ⚠️ 已弃用（蓝牙太慢），只留作参考 |
| `ESP32-S3-RS485-CAN-Demo\` | 微雪官方 Demo | 参考 |

---

# 📖 第二部分：新用户操作

1. 用 VS Code + PlatformIO 打开 `ESP32 for WiFi CAN Custom\`；
2. USB 线接板子 **USB 口**（两个 Type-C 中标 USB 的那个），点击 **→ Upload** 编译下载；
3. 首次使用连 `ESP32-WiFi-CAN`（密码 `12345678`）→ 浏览器打开 `http://192.168.4.1` → ⚙️ 配置 STA 热点信息 → 保存一次，之后全自动。

> 详细操作（三种使用方式、Python 客户端、Web 控制台）见 `ESP32 for WiFi CAN Custom\README.md`。

---

# 🔧 第三部分：深度开发参考

- 人类侧：`ESP32 for WiFi CAN Custom\README.md`（三部分：用户手册/开发者参考/技术内幕——帧协议、Web API、Python API、FreeRTOS 架构、性能实测）；
- **AI 侧：`AGENTS.md`**（协议结论、批帧协商、性能实测、已知坑、开发测试流程）。
