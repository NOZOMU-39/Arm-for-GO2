# arm_protocol — 脉塔电机协议库

把"转 30°"翻译成电机听得懂的字节、把电机回话译成人话——**只装脉塔电机协议**（V3/V4.3/V4.4 三族），纯 Python、零 ROS 依赖，可脱离 ROS 单独测试。与交互界面 JS（index.html PROTO_CORE 段）同源，两实现用"黄金向量"逐字节对拍。

## 模块

| 文件 | 干什么 |
|---|---|
| `arm_protocol/bytes_ops.py` | 字节工具（i16/u16/i32/u32/f32 打包解包 + JS 舍入语义） |
| `arm_protocol/build.py` | 组帧（意图 → 8 字节命令帧，V3/V44 两族） |
| `arm_protocol/parse.py` | 回复解析（帧 → 人话+结构化 values，三协议分叉） |
| `arm_protocol/errors.py` | 错误位表与语义表（V3/V44 两套） |
| `arm_protocol/angles.py` | 方向/减速比/零点换算与设零数学（显示角 ↔ 协议角） |
| `tools/gen_golden.js` | 黄金向量生成器（从界面 JS 提标准答案） |
| `tools/gen_rand_vectors.js` | 随机对拍题生成器 |
| `tools/real_probe.py` | 真机只读探测（0x9A/0x92） |
| `tools/full_read_probe.py` | 全只读命令真机探测（static/dynamic 两段） |
| `tools/a4_rate_test.py` | 0xA4 指令率测定（小角度摆动统计回复率） |
| `test/` | pytest 全套（黄金/随机/自含断言，源码树直跑） |

## 常用入口

```bash
# 测试（Windows/Jetson 均可，零 ROS 依赖）
python -m pytest test/ -q
# 协议改动后必须重生成双向量（输入交互界面 index.html）
node tools/gen_golden.js "<界面 index.html 路径>" test/golden_vectors.json
node tools/gen_rand_vectors.js "<界面 index.html 路径>" test/rand_vectors.json
```

> 边界：只装脉塔臂电机协议；IMU/手柄等外设协议归各自驱动包，不得并入。
