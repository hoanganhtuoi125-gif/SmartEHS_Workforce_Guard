@echo off
chcp 65001 >nul
title KHỞI CHẠY SMARTEHS WORKFORCE GUARD
cd /d "%~dp0"

echo [-] Đang khởi chạy SmartEHS Workforce Guard...
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Có lỗi xảy ra khi khởi chạy ứng dụng.
    pause
)

