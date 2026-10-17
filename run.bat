@echo off
chcp 65001 >nul
echo ====================================
echo   视频语音替换工具 - 快速启动
echo ====================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

REM 检查 FFmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 FFmpeg，请先安装 FFmpeg
    echo 安装方法: choco install ffmpeg
    pause
    exit /b 1
)

REM 检查依赖
echo [1/4] 检查 Python 依赖...
pip show openai-whisper >nul 2>&1
if errorlevel 1 (
    echo 首次运行，正在安装依赖...
    pip install -r requirements.txt
)

REM 检查 GPT-SoVITS
echo [2/4] 检查 GPT-SoVITS 服务...
curl -s http://127.0.0.1:9880/ >nul 2>&1
if errorlevel 1 (
    echo.
    echo [警告] GPT-SoVITS 服务未运行
    echo 请在另一个终端启动 GPT-SoVITS API:
    echo   cd GPT-SoVITS
    echo   python api.py -a 127.0.0.1 -p 9880
    echo.
    pause
)

echo [3/4] 准备运行环境...
echo [4/4] 启动主程序...
echo.

REM 显示帮助信息
python main.py --help

echo.
echo ====================================
echo 使用示例:
echo   python main.py video.mp4 ^
echo     --refer-audio ref.wav ^
echo     --refer-text "参考文本" ^
echo     --new-text "新台词"
echo ====================================
echo.
pause
