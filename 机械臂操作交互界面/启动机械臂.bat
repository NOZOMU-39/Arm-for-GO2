@echo off
chcp 65001 >nul
title 机械臂操作交互界面(开发模式)

set PY32=E:\Program Files\Python312-32\python.exe

if not exist "%PY32%" (
    echo [错误] 未找到 32 位 Python:%PY32%
    echo 请先安装 32 位 Python 3.12 到该目录,或修改本脚本开头的 PY32 路径。
    pause
    exit /b 1
)

echo ================================================
echo   机械臂操作交互界面 —— 开发模式启动
echo   (32 位 Python 直接运行,不打包)
echo ================================================
echo   1 = 真机模式(USB 直连 / ESP32 无线连接真实机械臂)
echo   2 = 模拟模式(无硬件,虚拟设备预览界面)
echo.
set /p MODE=请选择模式 [1/2],直接回车默认真机:

if "%MODE%"=="2" (
    echo.
    echo 以模拟模式启动...
    "%PY32%" main.py --mock
) else (
    echo.
    echo 以真机模式启动...
    "%PY32%" main.py
)

if errorlevel 1 (
    echo.
    echo [提示] 程序异常退出,请查看上方错误信息。
)
pause
