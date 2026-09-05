# AGENTS.md — 机械臂操作交互界面(AI 对接文档)

> 🤖 AI 对接文档(后续 AI 开发自动读取);人类唯一说明书见 **README.md**(三段式:这是什么/新用户操作/深度开发参考,含真机验证步骤)。
>
> **本模块强依赖其他模块,技术路线必须同步,不脱离项目独自选型**:
> - 电机协议/角度/限位经验全部来自 `电机上位机开发\index.html`(移植源,勿重新发明);
> - 无线通信走 `ESP32 for WiFi and BLE CAN\ESP32 for WiFi CAN Custom\examples\wifi_can_client.py`(本目录为原样复制,一行不改);
> - 通信模式/日志/注册表/限幅链与上位机同源(Device/Api 事件队列 + 50ms 拉取 + 三层日志)。
> 发现其他模块的问题,通过 `AI间交流\` 同步(更新前先问用户)。
>
> **目录定位（2026-09-05 用户定案）**：本界面＝Jetson 主控栈的 **Windows 操作前端**,与 `Jetson_Orin_NX\` 是客户端-服务端关系、**顶层目录保持独立不并入**;终态协议逻辑单一源化——**第 1 步在 arm_protocol 移植完成时执行**(PROTO_CORE 停止自维护、改指向 `Jetson_Orin_NX\ROS2\arm_ws\src\arm_protocol`),当前保留 USB/ESP32 直连(A 段只读验收/无 Jetson 兜底调试)。
>
> **⚠️ 协议改动联动纪律（2026-09-05 起）**：本文件是 arm_protocol 的 **JS 移植源**——改任何协议逻辑（组帧/解析/角度模型）后必须三同步：
> ① 界面侧 Node 回归（`测试\proto_core_test.js`）全绿 → ② Jetson 侧重跑两个黄金生成器（`arm_protocol\tools\gen_golden.js` + `gen_rand_vectors.js`，输入本 index.html）→ pytest 全绿 → ③ 同步 Jetson 副本 + colcon build。**不许只改一边**（黄金向量是 Python 版与 JS 版逐字节一致的验收尺）。

## 1. 项目定位与目录

- GO2 武器臂(5 关节)的操作交互界面:双通道(USB ZLG / ESP32 无线)、多电机实时曲线、位置控制(唯一控制方法)、限幅安全链。
- 32 位 Python 3.12(`E:\Program Files\Python312-32`) + PyInstaller onedir 打包,双击 exe 即用。
- 根目录:`机械臂操作交互界面\`

```
机械臂操作交互界面\
├── main.py            # pywebview 窗口 + js_api(Api 类)+ ZLGCan/MockCan/WiFiCANBridge + Device + 接收线程 + 文件日志
├── index.html         # 界面源码(单文件:HTML+CSS+JS;连接页+主界面;协议核心在 PROTO_CORE 标记段)
├── wifi_can_client.py # ESP32 无线客户端库(原样复制,勿改;仅在其上包装 WiFiCANBridge)
├── 启动机械臂.bat      # 开发模式(32 位 Python 直跑,可选模拟模式)
├── 打包机械臂.bat      # 一键打包(⚠️ GBK 编码,勿用编辑器改;改时用 Python GBK 重写)
├── 测试\proto_core_test.js  # Node vm 沙箱回归(52 项,无硬件无浏览器)
├── zlgcan.dll + kerneldlls\  # ZLG CAN 驱动(打包时从 ..\电机上位机开发\ 拷入)
├── 机械臂注册表.json   # 电机参数(独立临时参数,与上位机注册表互不影响;可导入上位机注册表)
├── 日志\调试日志_时间戳.txt   # 收发帧+操作名+界面摘要,每次运行一个文件(UTF-8)
├── README.md / AGENTS.md
└── dist\机械臂操作交互界面\   # 打包产物(exe 双击即用)
```

## 2. 通信层(三种后端统一接口,Device 无感)

| 后端 | 连接方式 | 说明 |
|---|---|---|
| `ZLGCan` | USB 直连 | 从上位机 main.py 原样移植(zlgcan.dll ctypes,枚举/波特率/收发) |
| `WiFiCANBridge` | ESP32 无线 | TCP 8888 命令与批帧反馈（当前交互界面仅用 TCP 单源） |
| `MockCan` | --mock 模拟 | 从上位机移植(回复逻辑同源,写死在线 1~4 号) |

**WiFiCANBridge 关键设计(勿改架构)**:
- 命令与反馈均走 TCP 8888：`client.send_can()` 发送并自动协商批帧 `0x0A13`，TCP 读线程批量解析 `0x03/0x05` 帧；交互界面已停用 UDP 8889 订阅（2026-08-26，避免双推挤占命令处理）;
- **不用 `client.monitor()`**:其 `_recv_frame` 持锁最长 0.5s 会阻塞发送。当前 TCP 读线程使用 socket 批量读取与流式解析，发送与接收互不阻塞;
- TCP 接收帧汇入线程安全 deque `_rxq`，按 (id,data) 签名 200ms 窗口去重；`Device._rx_loop` 每 1ms 排空;
- `set_baud` → `client.set_can_rate(kbps)`(0x0A10);仅非 1000 时调用 + 提示影响总线全部设备;
- 连接失败(OSError)返回中文错误;`bridge_dead` 置位后 transmit 快速失败;界面徽章变红;**不做自动重连**(半连通误判更危险);
- host 留空 → 走库内四级自动发现(AP 192.168.4.1 → 本机网段 → 热点网段 → 串口,2~5 秒)。

## 3. 协议关键结论(移植自上位机,勿再翻手册推翻)

- **CAN ID 三区制**:命令 `0x140+id`;回复 V3 回 `0x140+id`、V4 回 `0x240+id`(两路都认);广播 0x280;0x79 系统指令发/回 0x300;
- **0x92 多圈角字节位**:V3 读 **D1-D4**(小端 int32,0.01°/LSB,转子侧)——读 D4~7 会「恒 0」误判(2026-08-20 实证);V4 读 **D4-D7**;
- **0xA4 = 多圈绝对角目标,固件按「目标−当前」差值直接执行**:上位机必须先用 0x92 校准 rotDeg(否则差值 ±360N 空转);不做最近邻折算;0xA8 增量会污染固件角 ±360N(V3);
- **V3 = 转子侧单圈绝对值编码器**:断电丢圈号;0x63/0x64/0x60-62 实测无效;用「相位最近邻校准 + E0 档案」;E0 存**固件角**(0x92 校准后)非相位(存相位发 0° 偏 60°);显示 = `(rotDeg−E0)/gear×dir`;
- **V4**:0x92 多圈角直接显示(0.01°);设零必须 `0x80→0x64→0x76` 三步(只发 0x64 不生效);**勿用 0x94 做显示/曲线源**(转子单圈相位,基准不同 + 回绕震荡);
- **方向映射只在输入输出两端**:`out2rot = v×gear×dir` / `rot2out = v/gear×dir` / `amp2rot = v×dir`(电流不乘减速比)/ `spd2rot = |out2rot|`;内部坐标系不含 dir;
- **V3 0x9C 语义分叉**:`v9cSemantics`("angle"|"pulse")人工按实测写入,默认 pulse(D6-D7 编码器脉冲);**0.92 已到位时 0x9C 相位仅兜底**(快速反转取错圈 ±360N 坑,2026-08-25 实测修复);
- 轮询帧:`0x9A + 0x9C + 0x92`;勿用 0x94;V3 位置发送前 rotDeg 必须已校准;
- 固件角度限幅(0x20 索引 6/7)语义未定论,**本界面不提供**(只用软件限幅 limMinDeg/limMaxDeg)。

## 4. 机械臂新增逻辑(与上位机差异点)

1. **多电机轮询 `pollAll()`**:每周期(默认 500ms,**200~2000ms 可调**,UI hover 提示写明范围)对全部注册电机发 9A/9C/92(silent);各电机独立 `lastAngle[id]/lastAngleSrc[id]/chartBufs[id]`;
2. **设为零点(当前位置标定为输入值 X)**——用户确认语义:
   - V3:`E0 = rotDeg_cur − out2rot(X)`(纯函数 `v3E0ForX`),写注册表,不动固件;X=0 即原「记录机械零点」;
   - V4:`0x80→0x64→0x76` 三步(掉力警告确认);X≠0 额外写注册表 `E4 = X`(显示偏移);显示 = `rot2out(0x92)+E4`,发送目标 = `out2rot(deg−E4)`(E4=0 时与上位机行为一致);
3. **设置最大/最小角** = 软件限位 limMaxDeg/limMinDeg(saveLimits 逻辑 + 确认 + 清越限锁定);
4. **默认位置**:注册表字段 `defaultPosDeg`;「设置默认位置」= 记录当前显示角;「移动到默认位置」= 所有已设默认位置的电机逐个发 0xA4(确认框列出电机数);
5. **键盘 ↑/↓(按住连续、松手停)**:0xA2 速度指令(V3 无力矩字段;V4 tqMaxPct=50%);`v = min(速度输入, limMaxSpd)`;焦点守卫(输入框聚焦忽略);多键同按后者覆盖、两键都松才停;四重停止——松手/失焦/到限位(`kbLimitBlocked` 纯函数)/反馈超时 1.5s(发 0x81);
6. **扫描一致性**:逐 ID 1~32 发 0x9A 探测(silent),`consistencyDiff` 纯函数双向比对(注册无应答/在线未注册),弹警告**只警告不动作**;
7. **注册表导入**:`Api.import_registry()` 用 `webview.windows[0].create_file_dialog` 文件选择器(上位机位置不固定,必须自选文件),按 ID 合并(保留本注册表 E0/E4/限幅字段);
8. **连接页**:USB(枚举设备下拉)/ 无线(IP 输入,留空自动发现);波特率默认 1000;**hover 提示**统一 `[data-tip]` 组件,有范围/含义的值必须把完整范围+默认值写进提示;
9. **界面不显示指令名/指令号**(用户规定):按钮/提示/界面日志全中文功能名;指令名只写在文件日志 tx note(如 `0xA4 绝对位置(多圈目标 ...)`),供 AI 排查。
10. **上电位置(2026-09-06 用户定名,内部字段 restDeg/restDegDate/turnDeg)**——V4 甩动丢圈自动折回的参考档案(机制/工具见 Jetson arm_controller rest.py + tools/rest_calib.py,两侧 E4/restDeg 需同步):
    - **语义(用户定规)**:开电前**人工**把臂摆到的固定参考位(建议低势能+刻度/凸点)——不是掉电自落;换结构/换电机/重新设零后必须重标
    - 记录:`markRest()`——`restDeg = 显示角 − E4`(协议角基准,与 Jetson 校正工具读角同源);`restDegDate` 落当天;`turnDeg` 首次自动填(proto V43→10.0、V44→12.78,转子 1 圈输出角)
    - 按钮:工具栏「📍 记为上电位置」(选中电机,最左);V3 禁用(tip 说明);卡片每台统一一行(全含 V3:"—(V3 无此机制)")
    - **设零联动**:V4 设零完成(0x76 复位后)→ 若已标定过 → `m.restStale = true` + 横幅提示重标(卡片显示 ⚠️需重标);重标(记录)后清除
    - 动态提示 `updateMarkRestTip()`:选中变化/记录/设零后刷新 btnMarkRest tip(档案值/失效态/说明)
    - 字段透传:normMotors 扩展符保留全部字段;Jetson registry 权威副本与界面 registry 的 E4/restDeg 同步靠 sync_jetson_registry.py(见 §10)
11. **掉电自动校正 `autoCalibRest()`(2026-09-06 用户定稿,显式方向)**——急停/掉电后按规范摆到上电位置再上电,界面**自动**检测整圈差并 E4 直设修正(零 ROM 纯显示层):
    - 触发:①每次连接(showMainView 重置 autoCalibDone)②**电机重启恢复检测**(用户反馈"为何要断连重连"→ pollAll 尾监控:全离线→恢复 = 掉电重启 → 2.5s 后重置 autoCalibDone 自动重校)——界面挂着也能自动修正;
    - 判定:显示差 = restDeg − lastAngle ≈ N×turnDeg(残差≤2°)→ E4 = restDeg − raw 直设(勿叠加);非整圈 → 提示摆位/重标不误校;restStale(设零后)台跳过(等重标,防设零场景误报);
    - 显式:修正/警告都弹横幅 + 日志(丢圈 N 圈/非整圈提示),不静默
12. **无线设备发现(2026-09-06)**:连接页「🔍 搜索」→ `bridge.discover_wifi()`(Api 类!js_api 暴露 Api 非 Device——加错类 JS 拿不到,已踩) → `WiFiCANClient.scan_gateways()`(扫本机全部子网 8888 全收,**网段并行** ~1-2s)→ 下拉点选填入;连接成功记忆**实际 IP**(r.host,自动搜索也算)localStorage `wifi_host`,空地址连接优先试记忆(秒连)

## 5. 限幅安全链(完整继承 + 两处适配)

- `limitBlock` 发送前校验(所有运动指令统一入口)+ `monitorLimit` 运行中监控(角度/速度/电流任一越限 → **先同步发 0x81 停止再报警**,2° 死区回落解锁);
- 越限锁定 `limitAlarm[id]` 期间拦截一切运动指令,0x80/0x81/0x77/0x78 豁免(不走 limitBlock);归零在限幅外可用;
- **适配 1**:预发送拦截从 alert 改**横幅+日志**(无线环境 + 用户「提示用悬停」风格,不用阻塞弹窗);
- **适配 2**:多电机独立告警(limitAlarm 按 id),横幅与弹窗显示电机名;
- 报警弹窗三按钮:🛑 失能(0x80 掉力)/ 🏠 自动归零(二次确认,低速;V3 v3Home 回 E0、V4 moveToAngle(0));z-index 1001 确认框永远盖过报警弹窗(防按不到教训)。

## 6. 回归测试(每次改协议/限幅/数学后必跑)

```bash
node 测试\proto_core_test.js
```

- 52 项断言:字节工具边界、V3/V4 组帧字节布局、0x92 解析(D1-D4/D4-D7 分叉)、V3 相位最近邻(快速反转场景)、显示公式含 E0/dir、**设零点数学(V3 E0=rotDeg−out2rot(X);V4 E4 与 out2rot(deg−E4))**、limitBlock 判定矩阵、monitorLimit 状态机(先 0x81 后报警/死区解锁)、键盘限位停、chartAutoScale(±15%+2% 地板)、decode79Reply、扫描一致性比对、界面 HTML 无指令号;
- 套路:正则提取全部 `<script>` 段 → vm 执行(DOM/bridge stub)→ 断言;`setInterval` stub 为 noop、`setTimeout` 同步立即执行(否则事件循环不退出);**在 vm 内执行 `delete limitAlarm[4]` 等状态清理,不能 delete vm 返回值**;
- 真机验证步骤(精确到按钮)见 README「真机验证步骤」章节:只读验证(A 1~5)通过前不进入运动验证(B 6~10)。

## 7. 打包

```bash
powershell -NoProfile -Command "& '.\打包机械臂.bat'" </dev/null 2>&1 | iconv -f GBK -t UTF-8
```

- bat 是 GBK 编码,绝对不要用编辑器改;需改时用 Python `open(..., encoding='gbk', newline='\r\n')` 一次性重写;
- bat 三步:[1/3] 备份 dist 里 机械臂注册表.json + 日志\ → PyInstaller(--windowed --name 机械臂操作交互界面,--add-data index.html;.)→ [2/3] 从上位机目录拷 zlgcan.dll/kerneldlls + README.md → [3/3] 恢复;
- **交付约定**:每次源码/界面更新后必须重新打包;`dist\机械臂操作交互界面\` 是唯一最终交付物,整个文件夹拷走双击 exe 即用;打包后核验 exe、`_internal\index.html`(含本轮最新界面)、zlgcan.dll、kerneldlls\ 齐全。

## 8. 已知坑速查(移植继承 + 本模块新增)

| 坑 | 记忆点 |
|---|---|
| V3 0x92 读错字节位 | 读 D1-D4(勿 D4~7),否则恒 0/负值错位 |
| V3 0xA4 差值执行 | 必须先 0x92 校准 rotDeg;E0 存固件角非相位;不做最近邻折算 |
| V4 0x94 勿当显示源 | 转子单圈相位,基准不同 + 回绕 → 曲线震荡 |
| V4 0x64 设零 | 必须 0x80→0x64→0x76 三步(失能掉力警告) |
| V3 0x9C 相位校准虚跳 | 快速反转采样跳变>180° 取错圈 → 0.92 到位时相位仅兜底 |
| 0x92 帧勿直接改面板 | 被同周期 0x9A/0x9C 覆盖;缓存 lastAngle 由常驻渲染 |
| 固件限位(0x20 索引 6/7) | 语义未定论,本界面不提供;只用软件限幅 |
| log_line 静默失败 | 必须挂 Api 类(js_api 暴露 Api 非 Device)+ .catch 显式告警 |
| 轮询帧刷日志 | 轮询 9A/9C/92 收发静默(silent 参数 + 接收端判定两层),日志供人读 |
| WiFiCANClient 锁竞争 | 当前 TCP 批量读线程不用 monitor()；交互界面已停用 UDP 双推，避免反馈挤占命令 |
| 批帧协商常量 | CMD_ENABLE_BATCH=0x0A13(0x0A12 留给心跳看门狗勿占);直接复用库逻辑 |
| ESP32 空数据帧被丢 | 固件 len<7 丢弃:发送恒 8 字节补零(Device.send_frame 已 ljust) |
| 键盘误触发 | 焦点守卫 + 单电机视图激活 + 首次按下提示 + 四重停止 |
| 卡片输入框被刷新清空 | renderMotorCards 重建前保存输入值回填;每秒刷新只更新数字不重建 |
| 无线掉线 | bridge_dead 快速失败 + 徽章红 + 提示重连;不做自动重连 |
| 打包 GBK | bat 一次性生成后绝不编辑;改时 Python GBK 重写 |

## 9. 与上位机/ESP32 模块的接口约定

- **zlgcan.dll/kerneldlls**:打包时从 `..\电机上位机开发\` 拷入(不复制源码到本目录,避免双份维护);
- **wifi_can_client.py**:原样复制(一行不改),升级固件客户端时用新文件整体替换;协议变化同步记录到本文件与 `AI间交流\情报.md`(先问用户);
- **注册表互不影响**:本界面 机械臂注册表.json 独立;导入上位机注册表 = 一次性合并(文件选择器),不联动;
- 其他模块(IMU/摄像头/手柄)接入:左侧设备面板 `SIDEBAR_MODULES` 数据驱动 + `DEVICE_TABS` 设备类型标签,加条目 + 渲染函数即可,V1.0 已预留占位。

## 10. 遗留待办

- [ ] 真机只读验证(README 步骤 A)——通过前不开放运动验证;
- [ ] 真机运动验证(README 步骤 B)——小角度低速,末端关节优先;
- [ ] 无线实测(README 步骤 B10)——USB/无线对照;
- [ ] 协议只读特征探测增强:扫描时对在线电机追加 0x94/0x79 只读探测与注册表 proto 比对(当前只做在线/离线与 ID 核对);
- [ ] MockCan 注册表驱动化(当前写死在线 1~4,浏览器演示桥支持到 6);
- [ ] X2-7(V4.4)真机索引 6/7 验证(跟随上位机结论,本界面仍不提供固件限位);
- [ ] **上电位置与 Jetson 档案同步自动化**(2026-09-06 立):Jetson rest_calib --apply 改 E4、界面标定改 restDeg 后,双 registry 靠手工/外部工具同步——方向:Windows 侧 sync 脚本拉 Jetson 权威 registry 合并(限位/E4/restDeg/restDegDate/turnDeg),或二期语义化后界面直读 Jetson 档案;
- [ ] 上电位置重复性实测(2026-09-06 立):多次人工摆位读数散布,验证/收紧 rest_calib 容差(当前默认 2.0°);
- [ ] 设零耦合 SOP(2026-09-06 立):V4 设零 0x80 失能会让大臂带偏前臂链——界面提示/文档需写明"设零大臂前支撑前臂链"。
