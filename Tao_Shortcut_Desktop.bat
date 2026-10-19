@echo off
chcp 65001 >nul
title TẠO SHORTCUT DESKTOP
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $desk = [System.Environment]::GetFolderPath('Desktop'); $s = $ws.CreateShortcut([System.IO.Path]::Combine($desk, 'SmartEHS_Guard.lnk')); $exePath = [System.IO.Path]::Combine($PSScriptRoot, 'SmartEHS_Guard.exe'); if([System.IO.File]::Exists($exePath)){ $s.TargetPath = $exePath; } else { $s.TargetPath = [System.IO.Path]::Combine($PSScriptRoot, 'Chay_App_Python.bat'); }; $s.WorkingDirectory = $PSScriptRoot; $ico = [System.IO.Path]::Combine($PSScriptRoot, 'app_icon.ico'); if([System.IO.File]::Exists($ico)){ $s.IconLocation = $ico; }; $s.Description = 'Hệ Thống Giám Sát An Toàn Lao Động Smart EHS'; $s.Save(); Write-Host 'Đã tạo Shortcut Smart EHS ngoài Desktop thành công!'"
pause
