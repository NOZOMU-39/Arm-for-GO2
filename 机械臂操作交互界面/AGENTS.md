# AGENTS.md — 机械臂操作交互界面(AI 对接文档)

> 🤖 AI 对接文档(后续 AI 开发自动读取);人类唯一说明书见 **README.md**(三段式:这是什么/新用户操作/深度开发参考,含真机验证步骤)。
>
> **本模块强依赖其他模块,技术路线必须同步,不脱离项目独自选型**:
> - 电机协议/角度/限位经验全部来自 `电机上位机开发\index.html`(移植源,勿重新发明);
> - 无线通信走 `ESP32 for WiFi and BLE CAN\ESP32 for WiFi CAN Custom\examples\wifi_can_client.py`(本目录为原样复制,一行不改);
> - 通信模式/日志/注册表/限幅链与上位机同源(Device/Api 事件队列 + 50ms 拉取 + 三层日志)。
> 发现其他模块的问题,通过 `AI间交流\` 同步(更新前先问用户)。

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
├── 测试\proto_core_test.js  # Node vm 沙箱回归(46 项,无硬件无浏览器)
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
| `WiFiCANBridge` | ESP32 无线 | 新写:TCP 8888 命令(WiFiCANClient)+ UDP 8889 高频反馈(独立线程) |
| `MockCan` | --mock 模拟 | 从上位机移植(回复逻辑同源,写死在线 1~4 号) |

**WiFiCANBridge 关键设计(勿改架构)**:
- 命令走 `client.send_can()`(TCP,可靠,批帧协商 0x0A13 自动);反馈走 UDP 8889 订阅(`sendto b'\x01'` 即订阅,20s 续订,ESP32 30s 踢出);
- **不用 `client.monitor()`**:其 `_recv_frame` 持锁最长 0.5s 会阻塞发送。TCP 读线程自写循环调 `_recv_frame(timeout=0.05)`(50ms 短超时,发送最坏 +50ms 可接受),解析 0x03/0x05 帧入 `_rxq`;
- 两条读线程(TCP/UDP)汇入线程安全 deque `_rxq`,按 (id,data) 签名 200ms 窗口去重(UDP 权威);`Device._rx_loop` 每 1ms 排空;
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

- 46 项断言:字节工具边界、V3/V4 组帧字节布局、0x92 解析(D1-D4/D4-D7 分叉)、V3 相位最近邻(快速反转场景)、显示公式含 E0/dir、**设零点数学(V3 E0=rotDeg−out2rot(X);V4 E4 与 out2rot(deg−E4))**、limitBlock 判定矩阵、monitorLimit 状态机(先 0x81 后报警/死区解锁)、键盘限位停、chartAutoScale(±15%+2% 地板)、decode79Reply、扫描一致性比对、界面 HTML 无指令号;
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
| WiFiCANClient 锁竞争 | _recv_frame 持锁:TCP 读线程 50ms 短超时,不用 monitor();UDP 独立通道 |
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
- [ ] X2-7(V4.4)真机索引 6/7 验证(跟随上位机结论,本界面仍不提供固件限位)。
