@echo off
chcp 65001 >nul
echo ========================================================
echo   正在使用 PyInstaller 打包 Colab Model Hub 客户端...
echo ========================================================

py -3 -m PyInstaller ^
    --name="ColabModelHub" ^
    --windowed ^
    --onefile ^
    --clean ^
    --icon="gui/assets/app.ico" ^
    --add-data="gui;gui" ^
    --collect-data="colab_cli" ^
    app.py

echo.
if %ERRORLEVEL% EQU 0 (
    echo [成功] 打包完成！
    echo 正在同步复制最新可执行文件到根目录 ColabModelHub.exe ...
    copy /Y "dist\ColabModelHub.exe" "ColabModelHub.exe" >nul
    if %ERRORLEVEL% EQU 0 (
        echo [成功] 根目录 ColabModelHub.exe 已同步更新为最新版本！
    ) else (
        echo [警告] 无法覆盖根目录 ColabModelHub.exe，可能旧程序正在运行中，请关闭后再试。
    )
) else (
    echo [失败] 打包过程中出现错误，请检查日志。
)
pause
