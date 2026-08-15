@echo off
title 打包脉塔电机调试上位机

set PY32=E:\Program Files\Python312-32\python.exe

if not exist "%PY32%" (
    echo [错误] 未找到 32 位 Python:%PY32%
    echo 请先安装 32 位 Python 3.12 到该目录,或修改本脚本开头的 PY32 路径。
    pause
    exit /b 1
)

echo ================================================
echo   打包上位机(PyInstaller 32 位,onedir 模式)
echo   输出交付目录:dist\上位机\
echo ================================================

echo.
echo [1/3] 备份调试日志(防止打包重建目录时丢失)...
if exist "dist\上位机\调试日志.txt" copy /y "dist\上位机\调试日志.txt" "%TEMP%\shangweiji_log_backup.txt" >nul 2>&1

"%PY32%" -m PyInstaller --noconfirm --clean --windowed --name 上位机 ^
  --add-data "index.html;." ^
  --hidden-import clr ^
  --hidden-import clr_loader ^
  --hidden-import pythonnet ^
  --hidden-import webview.platforms.edgechromium ^
  --hidden-import webview.platforms.winforms ^
  main.py

if errorlevel 1 (
    echo.
    echo [错误] 打包失败,请检查上方输出信息。
    pause
    exit /b 1
)

echo.
echo [2/3] 复制驱动文件到交付目录...
copy /y zlgcan.dll "dist\上位机\" >nul
if exist kerneldlls (
    xcopy /e /i /y kerneldlls "dist\上位机\kerneldlls\" >nul
)
copy /y 使用说明.md "dist\上位机\" >nul

echo [3/3] 恢复调试日志...
if exist "%TEMP%\shangweiji_log_backup.txt" (
    copy /y "%TEMP%\shangweiji_log_backup.txt" "dist\上位机\调试日志.txt" >nul 2>&1
    del "%TEMP%\shangweiji_log_backup.txt" >nul 2>&1
)

echo ================================================
echo   完成!交付目录:dist\上位机\
echo   找到 上位机.exe 双击即可运行,无需安装。
echo   dist\上位机 文件夹可直接拷贝到任意电脑使用。
echo ================================================
pause
