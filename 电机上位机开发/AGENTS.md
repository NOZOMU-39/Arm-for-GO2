# AGENTS.md — 脉塔电机调试上位机(AI 对接文档)

> 🤖 AI 对接文档(后续 AI 开发自动读取);表层入口见 **README.md**,操作手册见 **使用说明.md**,技术路线见 **技术归档.md**。
>
> 本文件供 **AI 编程助手/未来自动化会话**直接阅读,快速恢复工程上下文。
> 人类阅读版见「技术归档.md」,用户操作版见「使用说明.md」。
> 配套项目:博士论文「无人平台武器臂的自动武器后坐扰动抑制与动态射击工作空间研究」(2026-11 开题、2029 送审),本上位机为工程侧配套调试工具。

## 1. 项目定位与目录

- 双协议脉塔伺服电机 CAN 调试上位机:pywebview 桌面 exe + index.html 全中文界面。
- **V3.91 协议**(RMD-X:X8-PRO、X6-S2,**旧款**)/ **V4.4 协议**(新款:X6-40、X2-7)。
- 32 位 Python 3.12(`E:\Program Files\Python312-32`) + PyInstaller 6.22.0 onedir 打包,双击 exe 即用。
- 根目录:`电机上位机开发\`

```
电机上位机开发\
├── main.py            # pywebview 窗口 + js_api(Api 类)+ zlgcan ctypes 封装 + 接收线程
├── index.html         # 界面源码(单文件:HTML+CSS+JS,双协议知识库,全部逻辑在此)
├── 启动上位机.bat      # 开发模式(32 位 Python 直跑,可选模拟模式)
├── 打包上位机.bat      # 一键打包(⚠️ GBK 编码,勿用编辑器改)
├── zlgcan.dll + kerneldlls\   # ZLG CAN 驱动(官方软件同款)
├── 电机注册表.json     # 电机参数(exe 同目录,自动读写)
├── 日志\调试日志_时间戳.txt   # 全部收发帧,每次运行一个文件(UTF-8,2026-08-19 起)
├── 使用说明.md / 技术归档.md / AGENTS.md
└── dist\上位机\        # 打包产物(exe 双击即用)
```

## 2. 协议关键结论(已查证,勿再翻手册推翻)

- **两代均无使能环节**:上电直接发闭环指令;0x80 关闭/0x81 停止。
- **V3.91**:0x20 仅有索引 0x01/0x02;**无多圈掉电保存**;0x60/0x61/0x62/0x63/0x64 实测全部无效(写 ROM 类被固件砍掉);**X8/X6-S2 = 转子侧单圈绝对值编码器** + **固件多圈角(0x92 可读,D1~4 int32 0.01°/LSB,会被 0xA8 增量污染成 ±360N)**;**0xA4 = 多圈绝对角目标,固件按「目标−当前」差值直接执行**(非最短路径、非单圈相位)→ 终版:0x92 轮询校准 rotDeg 到固件角 + **E0 存凸点固件角(含圈号,非相位!)** + 0xA4 发 R_t=E0+out2rot(deg);详见技术归档.md「问题 E」(含 12 条踩坑全记录);0x79 改 ID 发往固定地址 0x300(旧款拨杆设 ID,0x79 无效);0xA1 力矩在 **D4~5**;0x9C D6~7=16 位编码器脉冲(相位源)。
- **V4.4**:0x20 共 8 索引,**索引 4 = 多圈掉电保存**(置 1 掉电前自动存多圈,重启生效,失能时写);索引 5 = 设编号存 ROM;0xA1 力矩在 D2~3;0x9C D6~7 = 输出轴角度 int16(**1°/LSB,无 /100**);**0x64 当前位置设零:失能时才能写 ROM + 写后需 0x76 复位才生效**(→ v44SetZero 三步流程);**减速比=固件内置,指令角度即末端转轴角,注册表填 1(X2-7 实测确认)**。
- **两代均无全局方向反转指令**(0xA6 spinDirection 仅单次)→ 方向一致性只能软件映射;一体化 FOC 换相线不可行。
- 关键差异对照详见 技术归档.md 与 index.html 内 BUILD_V3/BUILD_V44。

## 3. 方向映射架构(index.html,本轮 2026-08-15 实现)

- 注册表条目字段:`dir: 1(正转,默认)| -1(反转)`;载入时两处归一化(`loadMotors` 与脚本顶部 localStorage 载入):`motors = motors.map(x => ({...x, dir: x.dir === -1 ? -1 : 1}))`。
- 核心函数(约 line 706~715):
  ```js
  gearOf(m)  // 减速比,缺省 1
  dirOf(m)   // 1|-1,缺省/0 归一 1
  out2rot(v,m) = v * gearOf(m) * dirOf(m)   // 输出轴→协议侧(组帧)
  rot2out(v,m) = v / gearOf(m) * dirOf(m)   // 协议侧→输出轴(显示)
  amp2rot(v,m) = v * dirOf(m)               // 力矩电流 A:只映方向不乘减速比
  spd2rot(v,m) = Math.abs(out2rot(v,m))     // 无符号上限速度字段(0xA4/0xA6/0xA9 D2~3)取幅度
  ```
- 接入点:所有闭环发送(v3Pos/v3Pos1/v3Speed/v3Torque/v44Pos/v44PosInc/v44Speed/v44Torque/v44ForcePos/v44FFSpd/v44FFTq);parseReply 内 `rm = motorById(n) || selMotor()` 按回复归属电机映射;V3 位置累积 v3PosFromEnc ×dir;0x92 校准 `t.revs = a/360*gear*dir`;updateStatusPanel 的 chart.feed 与面板数值;0xA6 负角度→取正+spinDirection 翻转。
- 不映射:0x280 广播、手动发帧(原样发送,UI 有提示)。

## 4. 掉电记忆实现

- V4:系统页「🔋 掉电记忆」按钮 → `v44FuncQuick(4, 1|0)` 发 `20 04 00 00 01 00 00 00`(重启生效,失能时写)。
- V3:系统页「🔧 掉电失位补偿」块(0x64 设零标定 + 说明固件边界与替代方案)。
- V4 设零:`v44SetZero()` 三步自动流程 **0x80(失能)→0x64(写 ROM)→0x76(复位)**,带强警告确认(失能掉力防下落);V3 的 `v3SetZero()` 保持单发 0x64 不动(旧固件支持存疑)。

## 5. 回归测试框架(无硬件验证界面逻辑)

- 环境:Node.js ≥18,不需要浏览器。临时测试脚本放 `C:\Users\NOZOMU\AppData\Local\Temp\claude\`,用完即删。
- 套路(参照 verify_fix8.js,28/28 过):
  ```js
  const js = html.slice(html.indexOf("<script>")+8, html.lastIndexOf("</script>"))
                  .replace(/\nboot\(\);\s*\n/, "\n");   // 提取纯 JS 并去掉自动 boot
  // 桩:mkEl(_children/innerHTML/textContent/value/style/getContext/getBoundingClientRect...)
  //     documentStub(getElementById 懒创建入 elStore)、ctxStub(Proxy 吸收一切)
  //     bridgeStub(send_frame 记入 sent[];get_registry 返回 {ok:true,data:REG} 传引用)
  //     setTimeout 同步立即执行
  vm.runInContext(js, ctx); vm.runInContext("boot()", ctx);
  ```
- **三个必踩的坑(历史教训)**:
  1. 脚本末尾自动 `boot()` 会撞 let 声明 TDZ → 必须正则去掉、手动 boot;
  2. **REG 必须在 boot() 之前初始化**——`vm.runInContext` 退出上下文边界时会立即 flush 微任务,loadMotors 的 await 恢复在此刻执行,宿主侧之后再设 REG 太晚;
  3. 测试主流程里**第一个 await 前要 `await new Promise(r => setImmediate(r))`** 排空微任务,否则 v3Pos 等函数同步执行时 motors 还是空的(sendMotor 报「请先在左侧注册表选择电机」)。
- 字节序断言用 pI16/pU16/pI32 两补码规则;V3 0xA1 力矩在 D4~5、V4 在 D2~3。

## 6. 打包

```bash
# bat 是 GBK 编码,绝对不要用编辑器改;用 powershell 调,并喂 </dev/null 解决 pause
powershell -NoProfile -Command "& '.\打包上位机.bat'" </dev/null 2>&1 | iconv -f GBK -t UTF-8
```
- 产物验证:`grep dist\上位机\_internal\index.html` 查本轮新增关键词(如「掉电记忆」「反转」「dirOf」)。
- bat 三步:[1/3] 备份 dist 里的 调试日志.txt(旧版遗留,新日志在 日志\ 子目录)→ PyInstaller → [2/3] 复制 zlgcan.dll/kerneldlls/使用说明.md → [3/3] 恢复日志。

## 7. 用户全局约定(必须遵守)

- 一律**中文**回复;每段回复第一句以「**我的朋友**」开头;操作完汇报(做了什么/改了哪个文件/变更概要)。
- 临时文件统一放 `C:\Users\NOZOMU\AppData\Local\Temp\claude\`,用完即删。
- **不得读「使用前说明.pdf」**。
- 识图用 `node C:\Users\NOZOMU\.claude\tools\vision.js "<路径>" "描述"`(DashScope qwen3.5-omni-plus),不要用 Read 读图片。
- 论文库 `E:\Work and Study Project\论文\`、资料库 `E:\Work and Study Project\资料库\`(脉塔协议手册在 `资料库\脉塔电机相关资料\`)。
- 用户是博士生;工程为博士论文配套,节奏上注意「结论先行、操作落地下游」。

## 8. 已知坑速查

| 坑 | 记忆点 |
|---|---|
| 协议选错清空 PID | 0x31/0x32 在 V3 是「写 RAM/ROM」,旧版工具误读会清六参数;恢复见 使用说明.md 常见问题 |
| V3 0x63/0x64 无效 | 旧款写 ROM 全砍;用 E0 档案+v3Home 归位 |
| V3 0xA4 是多圈直接差 | 0xA4=多圈绝对角目标,固件差值执行(非最短路径、非单圈相位);v3Pos 发 R_t=E0+out2rot(deg),勿拆分/折算/改 0xA8 |
| V3 0x92 是固件角校准源 | 读 **D1~4**(勿读 D4~7);轮询校准 rotDeg 到固件角;0xA4 正确性依赖此 |
| V3 E0 存固件角 | 凸点固件角(含圈号),非相位——存相位发 0° 会偏 60°(固件差 360N) |
| 0x92 面板常驻 | 0x92 帧勿直接改 kv(被 0x9A/0x9C 覆盖);缓存 v3_92info 由常驻面板追加 |
| V3 0x9C D6~7 非角度 | 16 位编码器脉冲(相位源,65536=360°) |
| 界面摘要落盘 | addLog 经 main.py log_line 写日志文件(排查必需) |
| 打包丢注册表 | 打包 bat 已备份/恢复 电机注册表.json(含 E0);改 bat 用字节级 GBK 安全补丁 |
| V3 电压恒 0 | 固件不回传,界面显示「固件不回传」,勿当电源故障 |
| 0x280 广播 | 需先 0x20 索引 0x02 失能编号滤波器;原样发送不按方向映射 |
| 扫描静默 | rawSend 第 5 参 silent=true;日志\ 子文件夹仍全量记录 |
| ID 冲突 | 添加/编辑两处已有拦截;总线物理同 ID 需改其中一台(旧款拨杆/V4 用 0x20 索引 5) |
| V4 0x64 设零不生效 | 协议要求失能写 ROM + 0x76 复位;v44SetZero 已自动 0x80→0x64→0x76 三步,V3 保持单发 |
| 曲线周期性置零 | 两因:auto-scale 无最小地板(满量程 2% floor)+ 0x92 无条件校准(≤5° 偏差过滤) |
| V4 减速比/0x9C 单位 | 固件内置减速比填 1;0x9C D6~7 是 1°/LSB 不是 0.01° |
| bat GBK | 断行问题见 §6 |
