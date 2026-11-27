@echo off
chcp 65001 >nul
title Colab Model Hub [开发调试模式]

echo ========================================================
echo   正在以源码开发模式启动 Colab Model Hub...
echo   (修改 Python 代码后无需打包，直接重新运行此脚本即可)
echo ========================================================

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

py -3 app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo --------------------------------------------------------
    echo [提示] 程序异常退出或报错，请查看上方 Python 堆栈日志。
    echo --------------------------------------------------------
    pause
)
