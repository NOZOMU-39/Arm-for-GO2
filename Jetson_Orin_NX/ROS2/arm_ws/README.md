# arm_ws — Jetson 机械臂控制软件

> 给机械臂主控（Jetson Orin NX）用的 ROS2 控制软件：把电脑上的操作指令变成电机动作、把电机状态读回来看得懂。
> 源码在 Windows 仓库（本目录），Jetson 上的 `~/ROS2/arm_ws` 是同步过去的构建副本。
> AI 开发对接见 `Jetson_Orin_NX\AGENTS.md`；架构决策见 `AI间交流\情报.md`。

---

# 📖 第一部分：这是什么

## 它能干什么

一条从"人想转 30°"到"电机转 30°"的链路，软件按块搭建，每块只管一件事：

```
操作指令 → [arm_controller 控制核心] → [arm_protocol 电机翻译官] → [can_bridge 通道] → can0 总线 → 电机
              （检查限幅/安全）          （编帧/译回复）            （收发）
电机回复 → 同一链路反向读回 → 显示成温度/角度/速度
```

| 软件包 | 大白话 | 状态 |
|---|---|---|
| arm_interfaces | "通信格式"字典（各块之间说话的标准） | ✅ 完成 |
| arm_protocol | 电机翻译官（把指令编成电机帧、把回复译成人话，三套协议 V3/V4.3/V4.4 都会） | ✅ 完成 |
| can_bridge | 软件 ↔ can0 总线之间的收发通道 | ✅ 完成（真机验证过） |
| arm_controller | 控制核心（档案、轮询、安全限幅、设零；二期扩展控制算法模块） | ⏳ 开发中 |
| tcp_gateway / arm_bringup | 接 Windows 操作界面（公用前端入口）/ 一键启动 | ⏳ 待做 |

## 它管什么、不管什么（地界，2026-09-05 定）

这套软件 = **臂本体（脉塔电机）控制栈**，只管狗背上的机械臂。看懂三条边界就不会迷路：

1. **命名规律**：`arm_` 开头的包 = 臂电机专用；IMU/摄像头/手柄等外设**各有各的包**（如 hi12s2_imu），不混进来——各设备协议随设备走，`arm_protocol` 只翻译脉塔电机协议；
2. **Windows 操作界面是"公用前端"**：它以后要看电机、IMU 曲线、摄像头画面……入口统一走 `tcp_gateway`（三期才接外设；视频走独立流，实验高频数据不出 Jetson，前端只看降频监控）；
3. **一个时刻只有一主**：Windows 界面和 Jetson 软件谁连总线，谁就是唯一主人——别两个控制端同时开（见下方安全须知）。

## 安全须知（先读）

- **上电顺序**：控制侧先上电 → 电机 24V 再上电 → 再连软件；
- **电机无抱闸**：失能/断电瞬间关节可能坠落——动电机前先做好机械防护；
- **V4 电机上电即"电子锁定"**（闭环保持，转动有阻尼，0x9A 显示"抱闸已锁定"是正常现象）——要自由转动必须先发失能；
- **只读优先**：真机调试一律先只读命令（0x9A/0x92 状态/角度），确认读数正常再谈运动指令；
- **别同时开两个控制端**（Windows 上位机/界面 + Jetson 软件同时连总线 = 双主会打架）。

---

# 🚀 第二部分：新用户操作

## 第 1 步：确认 Jetson 与源码（3 分钟）

1. Jetson 开机（短按两下电源键），能 `ssh nvidia@192.168.31.114`（密码 1，或免密 key）；
2. 确认 Jetson 上已有 `~/ROS2/arm_ws/src/`（没有就先在 Windows 仓库推送一次，见第 2 步）；
3. 打开 Jetson 终端，每次新开终端先执行（环境没写进 bashrc，必须手动）：
   ```bash
   source /opt/ros/humble/setup.bash && source ~/ROS2/arm_ws/install/setup.bash
   ```

## 第 2 步：把最新源码送到 Jetson（2 分钟，在 Windows 电脑执行）

```bash
scp -i ~/.ssh/id_ed25519_jetson_go2 -r "Jetson_Orin_NX/ROS2/arm_ws/src/<包名>" \
    nvidia@192.168.31.114:~/ROS2/arm_ws/src/
```
（<包名> 改你要同步的包；改了哪个包推哪个，不用全推。）

## 第 3 步：构建（2 分钟，在 Jetson 执行）

```bash
cd ~/ROS2/arm_ws
colcon build --packages-select <包名>
```
**验证点**：看到 `Summary: 1 package finished` 且无红字报错即成功。

## 第 4 步：跑起来看数据（5 分钟）

1. 终端 A 跑帧桥节点（Ctrl+C 可停）：
   ```bash
   source /opt/ros/humble/setup.bash && source ~/ROS2/arm_ws/install/setup.bash
   can_bridge
   ```
   应看到 `can0 已打开 @ can0`；
2. 终端 B 发一条只读查询（让 2 号电机报一下状态），再听回复：
   ```bash
   source /opt/ros/humble/setup.bash && source ~/ROS2/arm_ws/install/setup.bash
   ros2 topic pub --times 2 -r 1 --qos-reliability reliable /arm/can/tx \
       arm_interfaces/msg/CanFrame "{can_id: 322, dlc: 8, data: [154, 0, 0, 0, 0, 0, 0, 0]}"
   ros2 topic echo /arm/can/rx --qos-reliability reliable
   ```
   **验证点**：终端 A 出现 `TX id=0x142` 与 `RX id=0x242`（电机报的温度/电压回复）= 全链路打通。
   > 记住 `--qos-reliability reliable`：不带它软件收不到（QoS 不匹配，是踩坑教训）。

## 常见问题

| 现象 | 原因与处理 |
|---|---|
| 终端里 `ros2: 未找到命令` | 忘了 source（见第 1 步第 3 条） |
| 节点日志只有 TX 没有 RX | 早期版本漏启动接收线程——先 `colcon build` 更新到最新代码 |
| `ros2 topic echo` 收不到消息 | 加 `--qos-reliability reliable` |
| `ros2 run 包名 节点名` 说 No executable found | 直接用命令名跑（`can_bridge`），这是 setuptools 新版装的路径差异 |
| can0 打不开/报错 | 先 `ip -d link show can0` 看状态，ERROR-ACTIVE=正常；USB-CAN 没插好时拔插一下（热插拔自动恢复） |

---

# 🔧 第三部分：深度开发参考

## 目录结构

```
arm_ws/
├── src/
│   ├── arm_interfaces/   # 消息/服务定义（CanFrame/MotorState/RegistryEntry…）
│   ├── arm_protocol/     # 电机协议库（纯 Python，零 ROS 依赖）
│   │   ├── arm_protocol/  bytes_ops / build / errors / angles / parse
│   │   ├── tools/          gen_golden.js / gen_rand_vectors.js（黄金向量生成器）
│   │   │                    real_probe.py / full_read_probe.py（真机只读探测）
│   │   └── test/           pytest 5212 项 + golden/rand 向量 JSON
│   └── can_bridge/       # can0 帧桥（can_socket.py + bridge_node.py）
├── build/ install/ log/  # 构建产物（Jetson 生成，不入库）
└── README.md
```

## 验证体系（防协议 bug 的三道闸）

1. **黄金向量**：从交互界面 JS 版"标准答案"逐字节比对 Python 版（45 组帧 + 47 解析）；
2. **随机对拍**：750 组帧 + 4350 解析随机题，JS/Python 两实现同输入必须同输出；
3. **真机只读**：tools/real_probe.py（0x9A/0x92 探测）、full_read_probe.py（全只读命令 static/dynamic 两段）。
协议改动必须**三同步**：JS 源（交互界面）→ 重跑两个生成器 → 双端测试全绿（详见 `机械臂操作交互界面\AGENTS.md`）。

## 真机调试问题归档（2026-09-05，勿重蹈）

| 问题 | 根因 | 对策 |
|---|---|---|
| 节点只能发不能收 | 接收线程忘了 `start()` | 已修（线程对象创建≠启动） |
| CLI 发布节点收不到 | QoS History=SYSTEM_DEFAULT 与 Humble CLI 默认不匹配 | 显式 `KEEP_LAST` + CLI 加 `--qos-reliability reliable` |
| `ros2 run` No executable | 新版 setuptools 把脚本装到 bin/ | 直接跑命令名 |
| 回复地址认知 | V3 回命令域 0x140+id、V4 回 0x240+id | parse 双域接受（见情报） |
| 新终端没有 ros2 | bashrc 未配 ROS 环境 | 手动两个 source |

## 文档导航

| 想看什么 | 去哪 |
|---|---|
| AI 开发对接（同步/构建/踩坑） | `Jetson_Orin_NX\AGENTS.md` |
| 设备操作（开关机/CAN 硬件） | `Jetson_Orin_NX\README.md` |
| 架构决策/协议结论（长期记忆） | `AI间交流\情报.md` |
| 协议 JS 源与回归 | `机械臂操作交互界面\index.html`（PROTO_CORE 段）+ `测试\proto_core_test.js` |
