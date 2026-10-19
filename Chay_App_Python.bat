@echo off
chcp 65001 >nul
title KHỞI CHẠY SMARTEHS WORKFORCE GUARD (PYTHON)
cd /d "%~dp0"
echo [-] Đang khởi chạy hệ thống bằng môi trường Python...
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Co loi xay ra khi khoi chay ung dung.
    pause
)
