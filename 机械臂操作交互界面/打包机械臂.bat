@echo off
title 打包机械臂操作交互界面

set PY32=E:\Program Files\Python312-32\python.exe
set BASE=%~dp0

if not exist "%PY32%" (
    echo [错误] 未找到 32 位 Python:%PY32%
    echo 请先安装 32 位 Python 3.12 到该目录,或修改本脚本开头的 PY32 路径。
    pause
    exit /b 1
)

echo ================================================
echo   机械臂操作交互界面(PyInstaller 32 位,onedir 模式)
echo   打包输出目录:%BASE%dist\机械臂操作交互界面\
echo ================================================

echo.
echo [1/3] 备份注册表与日志(防止打包清理目录时丢失)...
if exist "%BASE%dist\机械臂操作交互界面\日志" xcopy /e /i /y "%BASE%dist\机械臂操作交互界面\日志" "%TEMP%\arm_logs_backup\" >nul 2>&1
if exist "%BASE%dist\机械臂操作交互界面\机械臂注册表.json" copy /y "%BASE%dist\机械臂操作交互界面\机械臂注册表.json" "%TEMP%\arm_reg_backup.json" >nul 2>&1

"%PY32%" -m PyInstaller --noconfirm --clean --windowed --name 机械臂操作交互界面 ^
  --add-data "index.html;." ^
  --hidden-import clr ^
  --hidden-import clr_loader ^
  --hidden-import pythonnet ^
  --hidden-import webview.platforms.edgechromium ^
  --hidden-import webview.platforms.winforms ^
  main.py

if errorlevel 1 (
    echo.
    echo [错误] 打包失败,请检查上方错误信息。
    pause
    exit /b 1
)

echo.
echo [2/3] 复制运行库与文档到输出目录...
if exist "%BASE%..\电机上位机开发\zlgcan.dll" (
    copy /y "%BASE%..\电机上位机开发\zlgcan.dll" "%BASE%dist\机械臂操作交互界面\" >nul
) else (
    echo [警告] 未找到 %BASE%..\电机上位机开发\zlgcan.dll,USB 直连不可用(无线连接不受影响)
)
if exist "%BASE%..\电机上位机开发\kerneldlls" (
    xcopy /e /i /y "%BASE%..\电机上位机开发\kerneldlls" "%BASE%dist\机械臂操作交互界面\kerneldlls\" >nul
)
copy /y "%BASE%README.md" "%BASE%dist\机械臂操作交互界面\" >nul

echo [3/3] 恢复注册表与日志...
if exist "%TEMP%\arm_reg_backup.json" (
    copy /y "%TEMP%\arm_reg_backup.json" "%BASE%dist\机械臂操作交互界面\机械臂注册表.json" >nul 2>&1
    del "%TEMP%\arm_reg_backup.json" >nul 2>&1
)
if exist "%TEMP%\arm_logs_backup" (
    xcopy /e /i /y "%TEMP%\arm_logs_backup" "%BASE%dist\机械臂操作交互界面\日志\" >nul 2>&1
    rmdir /s /q "%TEMP%\arm_logs_backup" >nul 2>&1
)

echo ================================================
echo   打包完成!输出目录:%BASE%dist\机械臂操作交互界面\
echo   找到 机械臂操作交互界面.exe 双击即可使用,无需安装。
echo   dist 文件夹可直接拷贝到其他电脑使用。
echo ================================================
pause
