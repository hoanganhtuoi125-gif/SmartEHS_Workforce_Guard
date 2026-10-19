#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
SMART EHS - HỆ THỐNG GIÁM SÁT AN TOÀN LAO ĐỘNG & ĐIỂM DANH ĐA CAMERA
Unified Application Entry Point (Điểm khởi chạy ứng dụng chính)
=============================================================================
"""

import os
import sys

# 1. Thiết lập bảng mã UTF-8 cho console Windows
if hasattr(sys.stdout, 'reconfigure'):
    try:
        getattr(sys.stdout, 'reconfigure')(encoding='utf-8', errors='replace')
        getattr(sys.stderr, 'reconfigure')(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 2. Định vị thư mục gốc của ứng dụng (Hỗ trợ chạy trực tiếp và chạy qua đóng gói .EXE PyInstaller)
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
    # Tự động nạp toàn bộ thư viện C++/DLL trong _internal và các thư mục .libs
    internal_dir = os.path.join(APP_DIR, "_internal")
    if os.path.isdir(internal_dir):
        if hasattr(os, 'add_dll_directory'):
            try:
                os.add_dll_directory(internal_dir)
                for item in os.listdir(internal_dir):
                    sub = os.path.join(internal_dir, item)
                    if os.path.isdir(sub) and item.endswith('.libs'):
                        try:
                            os.add_dll_directory(sub)
                        except Exception:
                            pass
            except Exception:
                pass
        os.environ['PATH'] = internal_dir + os.pathsep + os.environ.get('PATH', '')
    
    # Thiết lập biến môi trường Tcl/Tk phòng trường hợp PyInstaller thiếu hook
    for tcl_candidate in [os.path.join(APP_DIR, "lib", "tcl8.6"), os.path.join(internal_dir, "tcl8.6")]:
        if os.path.isdir(tcl_candidate):
            os.environ['TCL_LIBRARY'] = tcl_candidate
            break
    for tk_candidate in [os.path.join(APP_DIR, "lib", "tk8.6"), os.path.join(internal_dir, "tk8.6")]:
        if os.path.isdir(tk_candidate):
            os.environ['TK_LIBRARY'] = tk_candidate
            break
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(APP_DIR)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# 3. Tự động kiểm tra và khởi tạo các thư mục runtime cần thiết
REQUIRED_DIRS = [
    "models",
    "faces",
    "violations",
    "strangers",
    "temp_voice"
]

for d in REQUIRED_DIRS:
    d_path = os.path.join(APP_DIR, d)
    if not os.path.exists(d_path):
        os.makedirs(d_path, exist_ok=True)


def main():
    import tkinter as tk
    from tkinter import messagebox
    
    try:
        from main_app_dual_cam import SmartEHSManagementApp
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print(f" LỖI KHỞI ĐỘNG HỆ THỐNG:\n{err_msg}")
        root_err = tk.Tk()
        root_err.withdraw()
        messagebox.showerror(
            "Lỗi Khởi Động Smart EHS",
            f"Không thể nạp module hệ thống:\n{e}\n\nVui lòng kiểm tra lại môi trường hoặc file log."
        )
        return

    root = tk.Tk()
    
 
    icon_path = os.path.join(APP_DIR, "app_icon.ico")
    if not os.path.exists(icon_path):
        icon_path = os.path.join(APP_DIR, "web", "static", "favicon.ico")
    if os.path.exists(icon_path):
        try:
            root.iconbitmap(icon_path)
        except Exception:
            pass

    app = SmartEHSManagementApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
