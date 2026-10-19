import os
import sys
# Gỡ bỏ các biến môi trường CA bundle (như của PostgreSQL) làm sai lệch chứng chỉ camera nội bộ
os.environ.pop('CURL_CA_BUNDLE', None)
os.environ.pop('REQUESTS_CA_BUNDLE', None)
os.environ.pop('SSL_CERT_FILE', None)

import time
import tkinter as tk
from tkinter import ttk, colorchooser, messagebox
import copy
import threading
import cv2

class CameraEditDialog(tk.Toplevel):
    """ Dialog thêm / sửa thông tin Camera chuyên nghiệp """
    def __init__(self, parent, camera_data=None, on_save_cb=None):
        super().__init__(parent)
        default_cam: dict[str, object] = {
            "id": f"cam_{int(time.time())}",
            "name": "Camera Giám Sát Mới",
            "type": "webcam",
            "source": 0,
            "role": "ppe"
        }
        self.camera_data: dict[str, object] = copy.deepcopy(camera_data) if camera_data else default_cam
        self.on_save_cb = on_save_cb
        self.is_edit = camera_data is not None

        self.title("✏️ SỬA CAMERA" if self.is_edit else "➕ THÊM CAMERA MỚI")
        self.geometry("490x440")
        self.resizable(False, False)
        self.configure(bg="#1e293b")
        self.transient(parent)
        self.grab_set()

        self._build_ui()

    def _build_ui(self):
        pad_x, pad_y = 15, 8
        f_main = tk.Frame(self, bg="#1e293b")
        f_main.pack(fill=tk.BOTH, expand=True, padx=pad_x, pady=pad_y)

        # 1. Tên Camera
        tk.Label(f_main, text="Tên nhận diện Camera:", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.entry_name = tk.Entry(f_main, font=("Segoe UI", 10), bg="#0f172a", fg="white", insertbackground="white", bd=1)
        self.entry_name.insert(0, str(self.camera_data.get("name", "Camera Giám Sát")))
        self.entry_name.pack(fill=tk.X, pady=(2, 8))

        # 2. Phân loại Camera
        tk.Label(f_main, text="Loại Camera kết nối:", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.cam_type_var = tk.StringVar(value=str(self.camera_data.get("type", "rtsp")))
        f_types = tk.Frame(f_main, bg="#1e293b")
        f_types.pack(fill=tk.X, pady=(2, 8))

        tk.Radiobutton(f_types, text="Webcam USB", variable=self.cam_type_var, value="webcam",
                       bg="#1e293b", fg="white", selectcolor="#0f172a", activebackground="#1e293b",
                       command=self._on_type_change).pack(side=tk.LEFT, padx=(0, 10))
        tk.Radiobutton(f_types, text="RTSP Stream IP", variable=self.cam_type_var, value="rtsp",
                       bg="#1e293b", fg="white", selectcolor="#0f172a", activebackground="#1e293b",
                       command=self._on_type_change).pack(side=tk.LEFT, padx=10)
        tk.Radiobutton(f_types, text="Tapo PTZ Thông Minh", variable=self.cam_type_var, value="tapo",
                       bg="#1e293b", fg="white", selectcolor="#0f172a", activebackground="#1e293b",
                       command=self._on_type_change).pack(side=tk.LEFT, padx=10)

        # 3. Nguồn kết nối
        self.f_src_box = tk.LabelFrame(f_main, text="Chi Tiết Nguồn Camera", font=("Segoe UI", 9, "bold"), bg="#0f172a", fg="#38bdf8", bd=1)
        self.f_src_box.pack(fill=tk.X, pady=(4, 8), padx=2)

        # 3A. Khung chọn Webcam USB
        self.f_webcam_picker = tk.Frame(self.f_src_box, bg="#0f172a")
        tk.Label(self.f_webcam_picker, text="Chọn cổng Webcam trên máy tính:", font=("Segoe UI", 8), bg="#0f172a", fg="#cbd5e1").pack(anchor="w", padx=6, pady=(4, 2))
        
        cur_src = str(self.camera_data.get("source", "0"))
        self.cb_webcam = ttk.Combobox(self.f_webcam_picker, font=("Segoe UI", 9), state="readonly",
                                      values=[
                                          "0 - Webcam 0 (Mặc định / USB Camera)",
                                          "1 - Webcam 1 (Webcam phụ / Integrated Camera)",
                                          "2 - Webcam 2",
                                          "3 - Webcam 3"
                                      ])
        if cur_src == "1":
            self.cb_webcam.current(1)
        elif cur_src == "2":
            self.cb_webcam.current(2)
        elif cur_src == "3":
            self.cb_webcam.current(3)
        else:
            self.cb_webcam.current(0)
        self.cb_webcam.pack(fill=tk.X, padx=6, pady=(0, 4))

        # 3B. Khung nhập URL RTSP
        self.f_rtsp_box = tk.Frame(self.f_src_box, bg="#0f172a")
        self.lbl_src = tk.Label(self.f_rtsp_box, text="RTSP Stream URL:", font=("Segoe UI", 8), bg="#0f172a", fg="#cbd5e1")
        self.lbl_src.pack(anchor="w", padx=6, pady=(4, 2))

        self.entry_src = tk.Entry(self.f_rtsp_box, font=("Segoe UI", 9), bg="#1e293b", fg="white", insertbackground="white", bd=1)
        self.entry_src.insert(0, str(self.camera_data.get("source", "")))
        self.entry_src.pack(fill=tk.X, padx=6, pady=(0, 4))

        # 3C. Khung mở rộng cho Tapo IP
        self.f_tapo_extra = tk.Frame(self.f_src_box, bg="#0f172a")
        
        tk.Label(self.f_tapo_extra, text="IP Tapo:", font=("Segoe UI", 8), bg="#0f172a", fg="#cbd5e1").grid(row=0, column=0, sticky="w", padx=4)
        self.entry_tapo_ip = tk.Entry(self.f_tapo_extra, width=14, font=("Segoe UI", 9), bg="#1e293b", fg="white")
        self.entry_tapo_ip.insert(0, str(self.camera_data.get("tapo_ip", "") or ""))
        self.entry_tapo_ip.grid(row=0, column=1, padx=4, pady=2)
        self.entry_tapo_ip.bind("<KeyRelease>", self._sync_tapo_rtsp_url)

        tk.Label(self.f_tapo_extra, text="User:", font=("Segoe UI", 8), bg="#0f172a", fg="#cbd5e1").grid(row=0, column=2, sticky="w", padx=4)
        self.entry_tapo_user = tk.Entry(self.f_tapo_extra, width=10, font=("Segoe UI", 9), bg="#1e293b", fg="white")
        self.entry_tapo_user.insert(0, str(self.camera_data.get("tapo_user", "") or ""))
        self.entry_tapo_user.grid(row=0, column=3, padx=4, pady=2)
        self.entry_tapo_user.bind("<KeyRelease>", self._sync_tapo_rtsp_url)

        tk.Label(self.f_tapo_extra, text="Mật khẩu Cam:", font=("Segoe UI", 8), bg="#0f172a", fg="#cbd5e1").grid(row=1, column=0, sticky="w", padx=4)
        self.entry_tapo_pass = tk.Entry(self.f_tapo_extra, width=14, show="*", font=("Segoe UI", 9), bg="#1e293b", fg="white")
        self.entry_tapo_pass.insert(0, str(self.camera_data.get("tapo_pass", "") or ""))
        self.entry_tapo_pass.grid(row=1, column=1, padx=4, pady=2)
        self.entry_tapo_pass.bind("<KeyRelease>", self._sync_tapo_rtsp_url)

        tk.Label(self.f_tapo_extra, text="ONVIF Port:", font=("Segoe UI", 8), bg="#0f172a", fg="#cbd5e1").grid(row=1, column=2, sticky="w", padx=4)
        self.entry_tapo_onvif = tk.Entry(self.f_tapo_extra, width=10, font=("Segoe UI", 9), bg="#1e293b", fg="white")
        self.entry_tapo_onvif.insert(0, str(self.camera_data.get("tapo_onvif_port", 2020)))
        self.entry_tapo_onvif.grid(row=1, column=3, padx=4, pady=2)

        tk.Label(self.f_tapo_extra, text="Pass App Tapo:", font=("Segoe UI", 8, "bold"), bg="#0f172a", fg="#fbbf24").grid(row=2, column=0, sticky="w", padx=4)
        cur_cloud_pass = str(self.camera_data.get("tapo_cloud_pass", "") or "").strip()
        self.entry_tapo_cloud_pass = tk.Entry(self.f_tapo_extra, width=14, show="*", font=("Segoe UI", 9), bg="#1e293b", fg="white")
        self.entry_tapo_cloud_pass.insert(0, cur_cloud_pass)
        self.entry_tapo_cloud_pass.grid(row=2, column=1, padx=4, pady=2)

        self.btn_test_spk = tk.Button(self.f_tapo_extra, text="🔊 TEST LOA TAPO", font=("Segoe UI", 8, "bold"),
                                       bg="#0284c7", fg="white", activebackground="#0369a1", bd=0, padx=6, pady=2,
                                       cursor="hand2", command=self._action_test_speaker)
        self.btn_test_spk.grid(row=2, column=2, columnspan=2, sticky="ew", padx=4, pady=2)

        lbl_tapo_hint = tk.Label(self.f_tapo_extra,
                                 text="💡 'Pass App Tapo' là mật khẩu tài khoản TP-Link đăng nhập trên điện thoại.",
                                 font=("Segoe UI", 7, "italic"), bg="#0f172a", fg="#94a3b8")
        lbl_tapo_hint.grid(row=3, column=0, columnspan=4, sticky="w", padx=4, pady=(0, 2))

        # Nút Test Tín hiệu Camera
        self.btn_test_cam = tk.Button(self.f_src_box, text="🔍 KIỂM TRA TÍN HIỆU CAMERA", font=("Segoe UI", 8, "bold"),
                                      bg="#0369a1", fg="white", activebackground="#0284c7", bd=0, padx=8, pady=4,
                                      cursor="hand2", command=self._action_test_camera_stream)
        self.btn_test_cam.pack(fill=tk.X, padx=6, pady=(4, 6))

        # 4. Vai trò Camera
        tk.Label(f_main, text="Mục đích xử lý AI:", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.role_var = tk.StringVar(value=str(self.camera_data.get("role", "ppe")))
        f_roles = tk.Frame(f_main, bg="#1e293b")
        f_roles.pack(fill=tk.X, pady=(2, 10))

        tk.Radiobutton(f_roles, text="Quét Nhân Sự & Người Lạ (Cổng)", variable=self.role_var, value="attendance",
                       bg="#1e293b", fg="#38bdf8", selectcolor="#0f172a", activebackground="#1e293b").pack(side=tk.LEFT, padx=(0, 10))
        tk.Radiobutton(f_roles, text="Quét Bảo Hộ PPE & Vi Phạm (Hiện trường)", variable=self.role_var, value="ppe",
                       bg="#1e293b", fg="#f87171", selectcolor="#0f172a", activebackground="#1e293b").pack(side=tk.LEFT, padx=10)

        self._on_type_change()

        # Nút Lưu / Hủy
        btn_bar = tk.Frame(f_main, bg="#1e293b")
        btn_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=8)

        btn_save = tk.Button(btn_bar, text="💾 XÁC NHẬN LƯU", font=("Segoe UI", 9, "bold"), bg="#059669", fg="white",
                             activebackground="#047857", bd=0, padx=15, pady=6, cursor="hand2", command=self._save_camera)
        btn_save.pack(side=tk.RIGHT, padx=5)

        btn_cancel = tk.Button(btn_bar, text="HỦY", font=("Segoe UI", 9), bg="#475569", fg="white",
                               activebackground="#334155", bd=0, padx=12, pady=6, cursor="hand2", command=self.destroy)
        btn_cancel.pack(side=tk.RIGHT, padx=5)

    def _sync_tapo_rtsp_url(self, *args):
        import urllib.parse
        t_ip = self.entry_tapo_ip.get().strip()
        t_user = self.entry_tapo_user.get().strip()
        t_pass = self.entry_tapo_pass.get().strip()
        if t_ip and t_user:
            enc_pass = urllib.parse.quote(t_pass, safe='')
            rtsp_gen = f"rtsp://{t_user}:{enc_pass}@{t_ip}:554/stream1"
            self.entry_src.delete(0, tk.END)
            self.entry_src.insert(0, rtsp_gen)

    def _action_test_camera_stream(self):
        import urllib.parse
        c_type = self.cam_type_var.get()
        if c_type == "webcam":
            selected_str = self.cb_webcam.get()
            cam_idx = 0
            for part in selected_str.split():
                if part.isdigit():
                    cam_idx = int(part)
                    break
            test_src = cam_idx
            is_usb = True
        elif c_type == "tapo":
            self._sync_tapo_rtsp_url()
            test_src = self.entry_src.get().strip()
            is_usb = False
        else:
            test_src = self.entry_src.get().strip()
            is_usb = False

        self.btn_test_cam.config(text="⏳ Đang kiểm tra tín hiệu...", state=tk.DISABLED)

        def run_test():
            ok = False
            msg = ""
            cap = None
            try:
                if is_usb:
                    cap = cv2.VideoCapture(int(test_src), cv2.CAP_DSHOW)
                else:
                    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;3000000|timeout;3000000"
                    cap = cv2.VideoCapture(str(test_src), cv2.CAP_FFMPEG)
                if cap and cap.isOpened():
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        ok = True
                        h, w = frame.shape[:2]
                        msg = f"Đã nhận khung hình độ phân giải {w}x{h} mượt mà!"
                    else:
                        msg = "Mở được kết nối nhưng frame hình ảnh trống!"
                else:
                    msg = "Không thể mở luồng (thiết bị đang bận hoặc sai IP/mật khẩu)!"
            except Exception as e:
                msg = str(e)
            finally:
                if cap:
                    try:
                        cap.release()
                    except Exception:
                        pass

            def on_done():
                self.btn_test_cam.config(text="🔍 KIỂM TRA TÍN HIỆU CAMERA", state=tk.NORMAL)
                if ok:
                    messagebox.showinfo("KẾT NỐI THÀNH CÔNG", f"✅ Tín hiệu camera hoạt động tốt!\n{msg}")
                else:
                    messagebox.showwarning("KẾT NỐI THẤT BẠI", f"⚠️ Không nhận được tín hiệu:\n{msg}\n\nVui lòng kiểm tra lại thiết bị hoặc IP mạng.")

            self.after(0, on_done)

        threading.Thread(target=run_test, daemon=True).start()

    def _action_test_speaker(self):
        t_ip = self.entry_tapo_ip.get().strip()
        t_user = self.entry_tapo_user.get().strip()
        t_pass = self.entry_tapo_pass.get().strip()
        t_cloud = self.entry_tapo_cloud_pass.get().strip()

        if not t_cloud:
            messagebox.showwarning(
                "CHƯA NHẬP MẬT KHẨU APP TAPO",
                "Vui lòng nhập 'Pass App Tapo' (mật khẩu tài khoản TP-Link dùng đăng nhập trên điện thoại) trước khi bấm Test Loa!\n\n"
                "Lưu ý: Camera Tapo C200 không dùng Camera Account để điều khiển còi/loa được."
            )
            return

        cam_info = {
            "type": "tapo",
            "tapo_ip": t_ip,
            "tapo_user": t_user,
            "tapo_pass": t_pass,
            "tapo_cloud_pass": t_cloud
        }
        from talkback_streamer import TalkbackStreamer
        import threading

        self.btn_test_spk.config(text="⏳ Đang gửi lệnh...", state=tk.DISABLED)

        def run_test():
            streamer = TalkbackStreamer()
            ok, msg = streamer.test_tapo_speaker(cam_info)
            def on_done():
                self.btn_test_spk.config(text="🔊 TEST LOA TAPO", state=tk.NORMAL)
                if ok:
                    messagebox.showinfo(
                        "THÀNH CÔNG",
                        f"{msg}\n\n"
                        "💡 Loa camera hoạt động bình thường!"
                    )
                else:
                    messagebox.showerror("LỖI KẾT NỐI LOA TAPO", msg)
            self.after(0, on_done)

        threading.Thread(target=run_test, daemon=True).start()

    def _on_type_change(self):
        c_type = self.cam_type_var.get()
        cur_name = self.entry_name.get().strip()
        if c_type == "webcam":
            self.f_rtsp_box.pack_forget()
            self.f_tapo_extra.pack_forget()
            self.f_webcam_picker.pack(fill=tk.X, padx=6, pady=(0, 4))
            # Nếu tên hiện tại đang ghi Tapo hoặc tên mặc định, tự động đổi sang Webcam USB
            if "tapo" in cur_name.lower() or cur_name == "Camera Giám Sát Mới" or not cur_name:
                w_str = self.cb_webcam.get().split()[0] if self.cb_webcam.get() else "0"
                self.entry_name.delete(0, tk.END)
                self.entry_name.insert(0, f"Webcam USB {w_str}")
        elif c_type == "tapo":
            self.f_webcam_picker.pack_forget()
            self.f_rtsp_box.pack(fill=tk.X, padx=6, pady=(0, 2))
            self.f_tapo_extra.pack(fill=tk.X, padx=6, pady=4)
            self._sync_tapo_rtsp_url()
            if "webcam" in cur_name.lower():
                self.entry_name.delete(0, tk.END)
                self.entry_name.insert(0, "Tapo C200 PTZ")
        else:
            self.f_webcam_picker.pack_forget()
            self.f_tapo_extra.pack_forget()
            self.f_rtsp_box.pack(fill=tk.X, padx=6, pady=(0, 4))

    def _save_camera(self):
        name = self.entry_name.get().strip()
        if not name:
            messagebox.showwarning("CẢNH BÁO", "Vui lòng nhập Tên Camera!")
            return

        c_type = self.cam_type_var.get()
        if c_type == "webcam":
            selected_str = self.cb_webcam.get()
            cam_idx = 0
            for part in selected_str.split():
                if part.isdigit():
                    cam_idx = int(part)
                    break
            source_val = cam_idx
            # Xóa sạch các thuộc tính Tapo thừa khi cấu hình là webcam
            for k in ["tapo_ip", "tapo_user", "tapo_pass", "tapo_cloud_pass", "tapo_rtsp_port", "tapo_onvif_port"]:
                self.camera_data.pop(k, None)
        elif c_type == "tapo":
            t_ip = self.entry_tapo_ip.get().strip()
            t_user = self.entry_tapo_user.get().strip()
            t_pass = self.entry_tapo_pass.get().strip()
            t_cloud = self.entry_tapo_cloud_pass.get().strip()
            try:
                t_onvif = int(self.entry_tapo_onvif.get().strip())
            except Exception:
                t_onvif = 2020

            import urllib.parse
            enc_pass = urllib.parse.quote(t_pass, safe='')
            source_val = f"rtsp://{t_user}:{enc_pass}@{t_ip}:554/stream1"
            self.camera_data["tapo_ip"] = t_ip
            self.camera_data["tapo_user"] = t_user
            self.camera_data["tapo_pass"] = t_pass
            self.camera_data["tapo_cloud_pass"] = t_cloud
            self.camera_data["tapo_rtsp_port"] = 554
            self.camera_data["tapo_onvif_port"] = t_onvif
        else:
            source_val = self.entry_src.get().strip()

        self.camera_data["name"] = name
        self.camera_data["type"] = c_type
        self.camera_data["source"] = source_val
        self.camera_data["role"] = self.role_var.get()

        if self.on_save_cb:
            self.on_save_cb(self.camera_data)
        self.destroy()


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, config_manager, on_save_callback=None):
        super().__init__(parent)
        self.title("⚙️ CÀI ĐẶT HỆ THỐNG SMART EHS")
        self.geometry("680x680")
        self.resizable(False, False)
        self.configure(bg="#0f172a")
        
        self.config_mgr = config_manager
        self.settings = self.config_mgr.settings
        self.on_save_callback = on_save_callback

        # Bản sao danh sách cameras đang chỉnh sửa
        self.working_cameras = copy.deepcopy(self.config_mgr.get_cameras())

        self.transient(parent)
        self.grab_set()

        self._build_ui()

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use('default')
        style.configure("TNotebook", background="#0f172a", borderwidth=0)
        style.configure("TNotebook.Tab", background="#1e293b", foreground="#cbd5e1", padding=[12, 6], font=("Segoe UI", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#2563eb")], foreground=[("selected", "#ffffff")])

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        # ==========================================
        # TAB 1: QUẢN LÝ ĐA CAMERA (MULTI-CAMERA)
        # ==========================================
        tab_cam = tk.Frame(notebook, bg="#1e293b")
        notebook.add(tab_cam, text=" 📹 Quản Lý Đa Camera ")

        lbl_desc = tk.Label(tab_cam, text="DANH SÁCH CÁC CAMERA TRONG HỆ THỐNG (TỰ ĐỘNG BỐ TRÍ LƯỚI HIỂN THỊ)",
                            font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#38bdf8")
        lbl_desc.pack(anchor="w", padx=12, pady=(10, 4))

        # Table hiển thị danh sách Camera
        tree_frame = tk.Frame(tab_cam, bg="#0f172a")
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        columns = ("id", "name", "type", "role", "source")
        self.cam_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=8, selectmode="browse")
        self.cam_tree.heading("id", text="Mã")
        self.cam_tree.heading("name", text="Tên Camera")
        self.cam_tree.heading("type", text="Phân Loại")
        self.cam_tree.heading("role", text="Nhiệm Vụ AI")
        self.cam_tree.heading("source", text="Nguồn Kết Nối")

        self.cam_tree.column("id", width=55, anchor="center")
        self.cam_tree.column("name", width=170)
        self.cam_tree.column("type", width=85, anchor="center")
        self.cam_tree.column("role", width=105, anchor="center")
        self.cam_tree.column("source", width=180)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.cam_tree.yview)
        self.cam_tree.configure(yscrollcommand=scrollbar.set)
        self.cam_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._refresh_cam_tree()

        # Thanh nút Thao tác Camera
        cam_act_bar = tk.Frame(tab_cam, bg="#1e293b")
        cam_act_bar.pack(fill=tk.X, padx=12, pady=6)

        btn_add_cam = tk.Button(cam_act_bar, text="➕ THÊM CAMERA MỚI", font=("Segoe UI", 9, "bold"), bg="#0284c7", fg="white",
                                activebackground="#0369a1", bd=0, padx=12, pady=5, cursor="hand2", command=self._action_add_cam)
        btn_add_cam.pack(side=tk.LEFT, padx=(0, 6))

        btn_edit_cam = tk.Button(cam_act_bar, text="✏️ SỬA CAMERA", font=("Segoe UI", 9, "bold"), bg="#d97706", fg="white",
                                 activebackground="#b45309", bd=0, padx=12, pady=5, cursor="hand2", command=self._action_edit_cam)
        btn_edit_cam.pack(side=tk.LEFT, padx=6)

        btn_del_cam = tk.Button(cam_act_bar, text="🗑️ XÓA CAMERA", font=("Segoe UI", 9, "bold"), bg="#ef4444", fg="white",
                                activebackground="#dc2626", bd=0, padx=12, pady=5, cursor="hand2", command=self._action_delete_cam)
        btn_del_cam.pack(side=tk.LEFT, padx=6)

        lbl_hint_layout = tk.Label(tab_cam, text="💡 Ghi chú: Các khung hình camera sẽ tự động chia đều lưới trên màn hình.\n• Nhấn 1 lần vào camera để phóng to toàn màn hình.\n• Nhấn đúp để thu nhỏ camera quay về lưới hiển thị.\n• Muốn giao tiếp/nói qua camera nào thì chỉ cần nhấn chọn camera đó.",
                                   font=("Segoe UI", 8), bg="#1e293b", fg="#94a3b8", justify=tk.LEFT)
        lbl_hint_layout.pack(anchor="w", padx=12, pady=(4, 10))

        # ==========================================
        # TAB 2: CẤU HÌNH TẮT/BẬT LOẠI PPE CAN SCAN
        # ==========================================
        tab_ppe = tk.Frame(notebook, bg="#1e293b")
        notebook.add(tab_ppe, text=" 🛡️ Chọn Loại PPE ")

        tk.Label(tab_ppe, text="TẮT/BẬT CÁC LOẠI THIẾT BỊ PPE CẦN QUÉT:", font=("Segoe UI", 10, "bold"), bg="#1e293b", fg="#38bdf8").pack(anchor="w", padx=15, pady=12)

        ppe_cfg = self.settings.get("ppe_enabled", {})
        self.var_helmet = tk.BooleanVar(value=ppe_cfg.get("helmet", True))
        self.var_vest = tk.BooleanVar(value=ppe_cfg.get("vest", True))
        self.var_gloves = tk.BooleanVar(value=ppe_cfg.get("gloves", False))
        self.var_glasses = tk.BooleanVar(value=ppe_cfg.get("glasses", False))
        self.var_boots = tk.BooleanVar(value=ppe_cfg.get("boots", False))

        tk.Checkbutton(tab_ppe, text="Mũ bảo hộ (Hardhat / Helmet)", variable=self.var_helmet, font=("Segoe UI", 10), bg="#1e293b", fg="#ecf0f1", selectcolor="#0f172a", activebackground="#1e293b").pack(anchor="w", padx=25, pady=5)
        tk.Checkbutton(tab_ppe, text="Áo phản quang (Safety Vest)", variable=self.var_vest, font=("Segoe UI", 10), bg="#1e293b", fg="#ecf0f1", selectcolor="#0f172a", activebackground="#1e293b").pack(anchor="w", padx=25, pady=5)
        tk.Checkbutton(tab_ppe, text="Găng tay bảo hộ (Gloves)", variable=self.var_gloves, font=("Segoe UI", 10), bg="#1e293b", fg="#ecf0f1", selectcolor="#0f172a", activebackground="#1e293b").pack(anchor="w", padx=25, pady=5)
        tk.Checkbutton(tab_ppe, text="Kính an toàn (Glasses)", variable=self.var_glasses, font=("Segoe UI", 10), bg="#1e293b", fg="#ecf0f1", selectcolor="#0f172a", activebackground="#1e293b").pack(anchor="w", padx=25, pady=5)
        tk.Checkbutton(tab_ppe, text="Giày bảo hộ (Boots)", variable=self.var_boots, font=("Segoe UI", 10), bg="#1e293b", fg="#ecf0f1", selectcolor="#0f172a", activebackground="#1e293b").pack(anchor="w", padx=25, pady=5)

        # ==========================================
        # TAB 3: NGƯỠNG ĐỘ TIN TƯỞNG & COOLDOWN
        # ==========================================
        tab_thresh = tk.Frame(notebook, bg="#1e293b")
        notebook.add(tab_thresh, text=" 🎯 Ngưỡng AI ")

        thresh_cfg = self.settings.get("thresholds", {})
        tk.Label(tab_thresh, text="Độ tin tưởng phát hiện PPE (YOLO Confidence):", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#ecf0f1").pack(anchor="w", padx=15, pady=(15, 2))
        self.scale_ppe_conf = tk.Scale(tab_thresh, from_=0.10, to=0.95, resolution=0.05, orient=tk.HORIZONTAL, bg="#1e293b", fg="#ecf0f1", highlightthickness=0)
        self.scale_ppe_conf.set(thresh_cfg.get("ppe_confidence", 0.45))
        self.scale_ppe_conf.pack(fill=tk.X, padx=20)

        tk.Label(tab_thresh, text="Độ tương đồng nhận diện khuôn mặt (Face Similarity):", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#ecf0f1").pack(anchor="w", padx=15, pady=(15, 2))
        self.scale_face_sim = tk.Scale(tab_thresh, from_=0.30, to=0.85, resolution=0.05, orient=tk.HORIZONTAL, bg="#1e293b", fg="#ecf0f1", highlightthickness=0)
        self.scale_face_sim.set(thresh_cfg.get("face_similarity", 0.50))
        self.scale_face_sim.pack(fill=tk.X, padx=20)

        tk.Label(tab_thresh, text="Thời gian giãn cách ghi nhận (Cooldown - Giây):", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#ecf0f1").pack(anchor="w", padx=15, pady=(15, 2))
        self.scale_cooldown = tk.Scale(tab_thresh, from_=5, to=120, resolution=5, orient=tk.HORIZONTAL, bg="#1e293b", fg="#ecf0f1", highlightthickness=0)
        self.scale_cooldown.set(thresh_cfg.get("cooldown_seconds", 30))
        self.scale_cooldown.pack(fill=tk.X, padx=20)

        # ==========================================
        # TAB 4: MÀU SẮC KHUNG
        # ==========================================
        tab_colors = tk.Frame(notebook, bg="#1e293b")
        notebook.add(tab_colors, text=" 🎨 Màu Khung ")

        color_cfg = self.settings.get("colors", {})
        self.color_pass = color_cfg.get("pass", "#00FF00")
        self.color_viol = color_cfg.get("violation", "#FF0000")

        frame_c1 = tk.Frame(tab_colors, bg="#1e293b")
        frame_c1.pack(fill=tk.X, padx=15, pady=15)
        tk.Label(frame_c1, text="Màu khung ĐẠT TIỂU CHUẨN:", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#ecf0f1").pack(side=tk.LEFT)
        self.btn_color_pass = tk.Button(frame_c1, bg=self.color_pass, width=6, command=self._pick_color_pass)
        self.btn_color_pass.pack(side=tk.RIGHT)

        frame_c2 = tk.Frame(tab_colors, bg="#1e293b")
        frame_c2.pack(fill=tk.X, padx=15, pady=15)
        tk.Label(frame_c2, text="Màu khung VI PHẠM PPE:", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#ecf0f1").pack(side=tk.LEFT)
        self.btn_color_viol = tk.Button(frame_c2, bg=self.color_viol, width=6, command=self._pick_color_viol)
        self.btn_color_viol.pack(side=tk.RIGHT)

        # ==========================================
        # TAB 5: BÁO CÁO ZALO, ÂM THANH & CẢNH BÁO
        # ==========================================
        tab_alert = tk.Frame(notebook, bg="#1e293b")
        notebook.add(tab_alert, text=" 🔔 Cảnh Báo & Âm Thanh ")

        # 1. Cấu hình Còi Bíp Cảnh Báo (Tắt / Bật theo yêu cầu)
        f_beep = tk.LabelFrame(tab_alert, text="ÂM THANH CÒI BÍP (BEEP ALERT)", font=("Segoe UI", 9, "bold"), bg="#0f172a", fg="#f87171", bd=1)
        f_beep.pack(fill=tk.X, padx=12, pady=6)

        self.var_beep_en = tk.BooleanVar(value=self.settings.get("beep_enabled", False))
        chk_beep = tk.Checkbutton(f_beep, text="Bật tiếng còi bíp cảnh báo (Mặc định: TẮT để không làm phiền)",
                                  variable=self.var_beep_en, font=("Segoe UI", 9, "bold"), bg="#0f172a", fg="#f87171",
                                  selectcolor="#1e293b", activebackground="#0f172a")
        chk_beep.pack(anchor="w", padx=10, pady=6)

        # 2. Cấu hình Cảnh báo Giọng nói Người Lạ (Bỏ hoàn toàn cảnh báo vi phạm PPE nhân sự)
        v_cfg = self.settings.get("voice", {})
        f_voice = tk.LabelFrame(tab_alert, text="CẢNH BÁO GIỌNG NÓI AN NINH (CHỈ DÀNH CHO NGƯỜI LẠ)", font=("Segoe UI", 9, "bold"), bg="#0f172a", fg="#fbbf24", bd=1)
        f_voice.pack(fill=tk.X, padx=12, pady=6)

        self.var_stranger_voice = tk.BooleanVar(value=v_cfg.get("stranger_enabled", v_cfg.get("enabled", True)))
        chk_stranger_v = tk.Checkbutton(f_voice, text="Bật phát giọng nói khi phát hiện NGƯỜI LẠ chưa đăng ký tại cổng",
                                        variable=self.var_stranger_voice, font=("Segoe UI", 9, "bold"), bg="#0f172a", fg="#fbbf24",
                                        selectcolor="#1e293b", activebackground="#0f172a")
        chk_stranger_v.pack(anchor="w", padx=10, pady=(6, 2))

        lbl_no_worker_v = tk.Label(f_voice, text="ℹ️ Cảnh báo giọng nói công nhân thiếu mũ/áo đã được loại bỏ hoàn toàn.",
                                   font=("Segoe UI", 8, "italic"), bg="#0f172a", fg="#94a3b8")
        lbl_no_worker_v.pack(anchor="w", padx=12, pady=(0, 4))

        f_vrow = tk.Frame(f_voice, bg="#0f172a")
        f_vrow.pack(fill=tk.X, padx=10, pady=4)

        tk.Label(f_vrow, text="Dãn cách phát cảnh báo (giây):", font=("Segoe UI", 8), bg="#0f172a", fg="#cbd5e1").grid(row=0, column=0, sticky="w")
        self.entry_voice_interval = tk.Entry(f_vrow, font=("Segoe UI", 9), bg="#1e293b", fg="white", insertbackground="white", bd=1, width=8)
        self.entry_voice_interval.insert(0, str(v_cfg.get("interval_seconds", 30)))
        self.entry_voice_interval.grid(row=0, column=1, sticky="w", padx=5)

        tk.Label(f_vrow, text="Giọng đọc:", font=("Segoe UI", 8), bg="#0f172a", fg="#cbd5e1").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.combo_voice = ttk.Combobox(f_vrow, values=["vi-VN-HoaiMyNeural (Nữ)", "vi-VN-NamMinhNeural (Nam)"], width=22, state="readonly")
        if "Nam" in v_cfg.get("voice_type", ""):
            self.combo_voice.current(1)
        else:
            self.combo_voice.current(0)
        self.combo_voice.grid(row=0, column=3, sticky="w", padx=5)

        btn_test_v = tk.Button(f_voice, text="🔊 NGHE THỬ CẢNH BÁO NGƯỜI LẠ", font=("Segoe UI", 8, "bold"),
                               bg="#d97706", fg="white", activebackground="#b45309", bd=0, pady=4, cursor="hand2", command=self._action_test_voice)
        btn_test_v.pack(fill=tk.X, padx=10, pady=(2, 6))

        # 3. Cấu hình Báo cáo Zalo
        z_cfg = self.settings.get("zalo", {})
        f_zalo = tk.LabelFrame(tab_alert, text="BÁO CÁO QUA ZALO KÈM ẢNH BẰNG CHỨNG", font=("Segoe UI", 9, "bold"), bg="#0f172a", fg="#38bdf8", bd=1)
        f_zalo.pack(fill=tk.X, padx=12, pady=6)

        self.var_zalo_en = tk.BooleanVar(value=z_cfg.get("enabled", True))
        chk_zalo = tk.Checkbutton(f_zalo, text="Kích hoạt tự động gửi cảnh báo vi phạm an toàn kèm ảnh qua Zalo", variable=self.var_zalo_en,
                                  font=("Segoe UI", 9, "bold"), bg="#0f172a", fg="#10b981", selectcolor="#1e293b", activebackground="#0f172a")
        chk_zalo.pack(anchor="w", padx=10, pady=4)

        tk.Label(f_zalo, text="Zalo Webhook URL (Bot, n8n, Make, Gateway):", font=("Segoe UI", 8), bg="#0f172a", fg="#cbd5e1").pack(anchor="w", padx=10, pady=(2, 1))
        self.entry_zalo_webhook = tk.Entry(f_zalo, font=("Segoe UI", 9), bg="#1e293b", fg="white", insertbackground="white", bd=1)
        self.entry_zalo_webhook.insert(0, z_cfg.get("webhook_url", ""))
        self.entry_zalo_webhook.pack(fill=tk.X, padx=10, pady=(0, 4))

        f_oa = tk.Frame(f_zalo, bg="#0f172a")
        f_oa.pack(fill=tk.X, padx=10, pady=2)

        tk.Label(f_oa, text="OA Token:", font=("Segoe UI", 8), bg="#0f172a", fg="#cbd5e1").grid(row=0, column=0, sticky="w")
        self.entry_oa_token = tk.Entry(f_oa, font=("Segoe UI", 9), bg="#1e293b", fg="white", insertbackground="white", bd=1, width=20)
        self.entry_oa_token.insert(0, z_cfg.get("oa_access_token", ""))
        self.entry_oa_token.grid(row=0, column=1, sticky="w", padx=4, pady=2)

        tk.Label(f_oa, text="User ID:", font=("Segoe UI", 8), bg="#0f172a", fg="#cbd5e1").grid(row=0, column=2, sticky="w", padx=(6, 0))
        self.entry_oa_user = tk.Entry(f_oa, font=("Segoe UI", 9), bg="#1e293b", fg="white", insertbackground="white", bd=1, width=16)
        self.entry_oa_user.insert(0, z_cfg.get("oa_user_id", ""))
        self.entry_oa_user.grid(row=0, column=3, sticky="w", padx=4, pady=2)

        btn_test_z = tk.Button(f_zalo, text="🔔 BẤM TEST GỬI THỬ ZALO (KÈM ẢNH)", font=("Segoe UI", 8, "bold"),
                               bg="#0284c7", fg="white", activebackground="#0369a1", bd=0, pady=4, cursor="hand2", command=self._action_test_zalo)
        btn_test_z.pack(fill=tk.X, padx=10, pady=6)

        # 4. Cấu hình Báo cáo Telegram Bot
        t_cfg = self.settings.get("telegram", {})
        f_tele = tk.LabelFrame(tab_alert, text="BÁO CÁO QUA TELEGRAM BOT", font=("Segoe UI", 9, "bold"), bg="#0f172a", fg="#38bdf8", bd=1)
        f_tele.pack(fill=tk.X, padx=12, pady=6)

        self.var_tele_en = tk.BooleanVar(value=t_cfg.get("enabled", True))
        chk_tele = tk.Checkbutton(f_tele, text="Kích hoạt tự động gửi cảnh báo vi phạm an toàn kèm ảnh qua Telegram", variable=self.var_tele_en,
                                  font=("Segoe UI", 9, "bold"), bg="#0f172a", fg="#10b981", selectcolor="#1e293b", activebackground="#0f172a")
        chk_tele.pack(anchor="w", padx=10, pady=4)

        tk.Label(f_tele, text="Bot Token (Tạo bot miễn phí từ @BotFather trên Telegram):", font=("Segoe UI", 8), bg="#0f172a", fg="#cbd5e1").pack(anchor="w", padx=10, pady=(2, 1))
        self.entry_tele_token = tk.Entry(f_tele, font=("Segoe UI", 9), bg="#1e293b", fg="white", insertbackground="white", bd=1)
        self.entry_tele_token.insert(0, t_cfg.get("bot_token", ""))
        self.entry_tele_token.pack(fill=tk.X, padx=10, pady=(0, 4))

        tk.Label(f_tele, text="Chat ID (ID người nhận hoặc ID Nhóm Telegram):", font=("Segoe UI", 8), bg="#0f172a", fg="#cbd5e1").pack(anchor="w", padx=10, pady=(2, 1))
        f_cid = tk.Frame(f_tele, bg="#0f172a")
        f_cid.pack(fill=tk.X, padx=10, pady=(0, 4))
        self.entry_tele_chatid = tk.Entry(f_cid, font=("Segoe UI", 9), bg="#1e293b", fg="white", insertbackground="white", bd=1)
        self.entry_tele_chatid.insert(0, t_cfg.get("chat_id", ""))
        self.entry_tele_chatid.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.btn_autodetect_tele = tk.Button(f_cid, text="🔍 Tự Động Lấy ID", font=("Segoe UI", 8, "bold"),
                                             bg="#334155", fg="#38bdf8", activebackground="#475569", bd=0, padx=8, pady=2,
                                             cursor="hand2", command=self._action_autodetect_chatid)
        self.btn_autodetect_tele.pack(side=tk.RIGHT, padx=(4, 0))

        lbl_tele_hint = tk.Label(f_tele, text="💡 Mẹo: Nhập Bot Token và Chat ID để nhận cảnh báo vi phạm an toàn qua Telegram.",
                                 font=("Segoe UI", 7, "italic"), bg="#0f172a", fg="#94a3b8")
        lbl_tele_hint.pack(anchor="w", padx=10, pady=(0, 4))

        self.btn_test_tele = tk.Button(f_tele, text="🔔 BẤM TEST GỬI THỬ TELEGRAM (KÈM ẢNH)", font=("Segoe UI", 8, "bold"),
                                       bg="#0284c7", fg="white", activebackground="#0369a1", bd=0, pady=4, cursor="hand2", command=self._action_test_telegram)
        self.btn_test_tele.pack(fill=tk.X, padx=10, pady=(2, 6))

        # ==========================================
        # BUTTON SAVE / CANCEL
        # ==========================================
        btn_frame = tk.Frame(self, bg="#0f172a")
        btn_frame.pack(fill=tk.X, padx=15, pady=12)

        btn_save = tk.Button(btn_frame, text="💾 LƯU CẤU HÌNH & TÁI KHỞI ĐỘNG HỆ THỐNG", font=("Segoe UI", 10, "bold"), bg="#059669", fg="white",
                             activebackground="#047857", bd=0, padx=16, pady=6, cursor="hand2", command=self._save_action)
        btn_save.pack(side=tk.RIGHT, padx=5)

        btn_cancel = tk.Button(btn_frame, text="HỦY BỎ", font=("Segoe UI", 10), bg="#475569", fg="white",
                               activebackground="#334155", bd=0, padx=14, pady=6, cursor="hand2", command=self.destroy)
        btn_cancel.pack(side=tk.RIGHT, padx=5)

    def _refresh_cam_tree(self):
        for item in self.cam_tree.get_children():
            self.cam_tree.delete(item)
        for cam in self.working_cameras:
            c_id = cam.get("id", "")
            c_name = cam.get("name", "")
            c_type = cam.get("type", "rtsp").upper()
            c_role = "Điểm danh" if cam.get("role") == "attendance" else "Bảo hộ PPE"
            c_src = str(cam.get("source", ""))
            if len(c_src) > 35:
                c_src = c_src[:32] + "..."
            self.cam_tree.insert("", tk.END, values=(c_id, c_name, c_type, c_role, c_src))

    def _action_add_cam(self):
        new_id = f"cam_{len(self.working_cameras) + 1}"
        new_cam_data = {
            "id": new_id,
            "name": f"CAM {len(self.working_cameras) + 1} - Camera Mới",
            "type": "webcam",
            "source": 0,
            "tapo_ip": "",
            "tapo_user": "",
            "tapo_pass": "",
            "tapo_cloud_pass": "",
            "tapo_rtsp_port": 554,
            "tapo_onvif_port": 2020,
            "role": "ppe"
        }
        def on_add(saved_data):
            self.working_cameras.append(saved_data)
            self._refresh_cam_tree()

        CameraEditDialog(self, camera_data=new_cam_data, on_save_cb=on_add)

    def _action_edit_cam(self):
        selected = self.cam_tree.selection()
        if not selected:
            messagebox.showinfo("CHÚ Ý", "Vui lòng chọn một camera trong danh sách để chỉnh sửa!")
            return
        idx = self.cam_tree.index(selected[0])
        cam_data = self.working_cameras[idx]

        def on_update(saved_data):
            self.working_cameras[idx] = saved_data
            self._refresh_cam_tree()

        CameraEditDialog(self, camera_data=cam_data, on_save_cb=on_update)

    def _action_delete_cam(self):
        selected = self.cam_tree.selection()
        if not selected:
            messagebox.showinfo("CHÚ Ý", "Vui lòng chọn một camera để xóa!")
            return
        if len(self.working_cameras) <= 1:
            messagebox.showwarning("CẢNH BÁO", "Hệ thống cần tối thiểu 1 Camera để hoạt động!")
            return
        idx = self.cam_tree.index(selected[0])
        cam_name = self.working_cameras[idx].get("name", "Camera")
        if messagebox.askyesno("XÁC NHẬN", f"Bạn có chắc chắn muốn xóa {cam_name} khỏi hệ thống?"):
            self.working_cameras.pop(idx)
            self._refresh_cam_tree()

    def _action_test_voice(self):
        try:
            from voice_notifier import VoiceNotifier
            vn = VoiceNotifier(self.config_mgr)
            vn.test_speak("Cảnh báo an ninh! Phát hiện người lạ chưa đăng ký tại cổng kiểm soát. Đề nghị kiểm tra danh tính.")
            messagebox.showinfo("THÔNG BÁO", "Đang phát thử nghiệm âm thanh cảnh báo người lạ qua loa!")
        except Exception as e:
            messagebox.showerror("LỖI", f"Không thể phát giọng nói:\n{e}")

    def _action_test_zalo(self):
        try:
            z_cfg = self.config_mgr.settings.setdefault("zalo", {})
            z_cfg["enabled"] = self.var_zalo_en.get()
            z_cfg["webhook_url"] = self.entry_zalo_webhook.get().strip()
            z_cfg["oa_access_token"] = self.entry_oa_token.get().strip()
            z_cfg["oa_user_id"] = self.entry_oa_user.get().strip()
            from zalo_notifier import ZaloNotifier
            zn = ZaloNotifier(self.config_mgr)
            zn.send_test_alert()
            messagebox.showinfo("THÔNG BÁO", "Đã gửi thông báo kiểm tra (kèm ảnh) tới Zalo!")
        except Exception as e:
            messagebox.showerror("LỖI", f"Không thể gửi thông báo Zalo:\n{e}")

    def _action_autodetect_chatid(self):
        token = self.entry_tele_token.get().strip()
        if not token:
            messagebox.showwarning("THIẾU TOKEN", "Vui lòng nhập Bot Token trước khi tìm Chat ID!")
            return

        self.btn_autodetect_tele.config(text="⏳ Đang tìm...", state=tk.DISABLED)

        def run_detect():
            from telegram_notifier import TelegramNotifier
            cid, msg = TelegramNotifier.detect_chat_id(token)
            def on_done():
                self.btn_autodetect_tele.config(text="🔍 Tự Động Lấy ID", state=tk.NORMAL)
                if cid:
                    self.entry_tele_chatid.delete(0, tk.END)
                    self.entry_tele_chatid.insert(0, cid)
                    messagebox.showinfo("TÌM THẤY CHAT ID", msg)
                else:
                    messagebox.showwarning("CHƯA TÌM THẤY CHAT ID", msg)
            self.after(0, on_done)

        threading.Thread(target=run_detect, daemon=True).start()

    def _action_test_telegram(self):
        token = self.entry_tele_token.get().strip()
        chat_id = self.entry_tele_chatid.get().strip()
        if not token or not chat_id:
            messagebox.showwarning("CHƯA ĐIỀN ĐỦ THÔNG TIN", "Vui lòng nhập Bot Token và Chat ID trước khi bấm Test!")
            return

        t_cfg = self.config_mgr.settings.setdefault("telegram", {})
        t_cfg["enabled"] = self.var_tele_en.get()
        t_cfg["bot_token"] = token
        t_cfg["chat_id"] = chat_id

        self.btn_test_tele.config(text="⏳ Đang gửi thử tới Telegram...", state=tk.DISABLED)

        def run_test():
            from telegram_notifier import TelegramNotifier
            tn = TelegramNotifier(self.config_mgr)
            ok, msg = tn.send_test_alert()
            def on_done():
                self.btn_test_tele.config(text="🔔 BẤM TEST GỬI THỬ TELEGRAM (KÈM ẢNH)", state=tk.NORMAL)
                if ok:
                    messagebox.showinfo("THÀNH CÔNG", msg)
                else:
                    messagebox.showerror("LỖI GỬI TELEGRAM", msg)
            self.after(0, on_done)

        threading.Thread(target=run_test, daemon=True).start()

    def _pick_color_pass(self):
        color = colorchooser.askcolor(title="Chọn màu khung ĐẠT", initialcolor=self.color_pass)
        if color[1]:
            self.color_pass = color[1]
            self.btn_color_pass.configure(bg=self.color_pass)

    def _pick_color_viol(self):
        color = colorchooser.askcolor(title="Chọn màu khung VI PHẠM", initialcolor=self.color_viol)
        if color[1]:
            self.color_viol = color[1]
            self.btn_color_viol.configure(bg=self.color_viol)

    def _save_action(self):
        try:
            # Đồng bộ lại cấu hình legacy cam_cfg từ cam1 & cam2 để các phân hệ cũ không bị ảnh hưởng
            cam1_cfg = next((c for c in self.working_cameras if c.get("role") == "attendance"), self.working_cameras[0])
            cam2_cfg = next((c for c in self.working_cameras if c.get("role") == "ppe"), self.working_cameras[-1])
            tapo_cam = next((c for c in self.working_cameras if c.get("type") == "tapo"), None)
            tapo_ip_val = tapo_cam.get("tapo_ip", "") if tapo_cam else self.settings.get("camera", {}).get("tapo_ip", "")
            tapo_user_val = tapo_cam.get("tapo_user", "") if tapo_cam else self.settings.get("camera", {}).get("tapo_user", "")
            tapo_pass_val = tapo_cam.get("tapo_pass", "") if tapo_cam else self.settings.get("camera", {}).get("tapo_pass", "")
            tapo_cloud_val = tapo_cam.get("tapo_cloud_pass", "") if tapo_cam else self.settings.get("camera", {}).get("tapo_cloud_pass", "")
            tapo_rtsp_val = int(tapo_cam.get("tapo_rtsp_port", 554)) if (tapo_cam and tapo_cam.get("tapo_rtsp_port")) else int(self.settings.get("camera", {}).get("tapo_rtsp_port", 554))
            tapo_onvif_val = int(tapo_cam.get("tapo_onvif_port", 2020)) if (tapo_cam and tapo_cam.get("tapo_onvif_port")) else int(self.settings.get("camera", {}).get("tapo_onvif_port", 2020))

            legacy_camera = {
                "cam_attendance_type": cam1_cfg.get("type", "webcam"),
                "webcam_index": int(cam1_cfg.get("source", 0)) if str(cam1_cfg.get("source")).isdigit() else 0,
                "cam_attendance_rtsp": str(cam1_cfg.get("source", "")),
                "tapo_ip": tapo_ip_val,
                "tapo_user": tapo_user_val,
                "tapo_pass": tapo_pass_val,
                "tapo_cloud_pass": tapo_cloud_val,
                "tapo_rtsp_port": tapo_rtsp_val,
                "tapo_onvif_port": tapo_onvif_val
            }

            new_settings = {
                "beep_enabled": self.var_beep_en.get(),
                "cameras": self.working_cameras,
                "camera": legacy_camera,
                "thresholds": {
                    "ppe_confidence": round(float(self.scale_ppe_conf.get()), 2),
                    "face_similarity": round(float(self.scale_face_sim.get()), 2),
                    "cooldown_seconds": int(self.scale_cooldown.get())
                },
                "ppe_enabled": {
                    "helmet": self.var_helmet.get(),
                    "vest": self.var_vest.get(),
                    "gloves": self.var_gloves.get(),
                    "glasses": self.var_glasses.get(),
                    "boots": self.var_boots.get()
                },
                "colors": {
                    "pass": self.color_pass,
                    "violation": self.color_viol,
                    "unknown": "#FF8C00"
                },
                "zalo": {
                    "enabled": self.var_zalo_en.get(),
                    "webhook_url": self.entry_zalo_webhook.get().strip(),
                    "oa_access_token": self.entry_oa_token.get().strip(),
                    "oa_user_id": self.entry_oa_user.get().strip(),
                    "cooldown_seconds": 45
                },
                "telegram": {
                    "enabled": self.var_tele_en.get(),
                    "bot_token": self.entry_tele_token.get().strip(),
                    "chat_id": self.entry_tele_chatid.get().strip(),
                    "cooldown_seconds": 30
                },
                "voice": {
                    "enabled": self.var_stranger_voice.get(),
                    "stranger_enabled": self.var_stranger_voice.get(),
                    "interval_seconds": int(self.entry_voice_interval.get().strip() or "30"),
                    "voice_type": "vi-VN-NamMinhNeural" if "Nam" in self.combo_voice.get() else "vi-VN-HoaiMyNeural"
                }
            }

            if self.config_mgr.save_settings(new_settings):
                cb = self.on_save_callback
                self.destroy()
                if cb:
                    cb()
        except Exception as e:
            messagebox.showerror("LỖI", f"Không thể lưu cấu hình:\n{e}")