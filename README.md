# Arm for GO2 — 项目工程使用说明

## 这是什么
GO2 武器臂工程：脉塔电机调试上位机、ESP32-S3 无线 CAN 通信、协议资料。AI 协作内容统一放在 `AI间交流\`。

## 目录
- `电机上位机开发\`：电机调试上位机（源码 + 打包产物 `dist\上位机\上位机.exe`）
- `ESP32 for WiFi and BLE CAN\`：ESP32-S3 CAN 无线中继（PlatformIO）
- `Database\`：脉塔协议手册与产品资料
- `AI间交流\`：AI 协作目录（项目上下文、安全需求、决策与规范、任务收件箱/发件箱）
- 结构图纸：`E:\Work and Study Project\无人平台武器臂\模型\`

## 人类常用操作
1. 运行上位机：`电机上位机开发\dist\上位机\上位机.exe`（双击即用）
2. 重新打包：双击 `电机上位机开发\打包上位机.bat`（GBK 编码，勿用编辑器改）
3. 烧录 ESP32：VS Code + PlatformIO 打开对应工程后 Upload
4. 协议手册：`Database\` 与 `E:\Work and Study Project\资料库\脉塔电机相关资料\`
