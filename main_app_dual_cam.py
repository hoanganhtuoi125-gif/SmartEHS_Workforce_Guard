import cv2
import time
import os
import threading
import asyncio
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk

# Import các Phân hệ
from config_manager import ConfigManager
from settings_dialog import SettingsDialog
from employee_manager_dialog import EmployeeManagerDialog
from pytorch_engine import PyTorchGPUEngine
from face_engine import InsightFaceEngine
from db_manager import AttendanceDatabase
from ui_renderer import render_camera_overlay, smart_fit_canvas, letterbox_canvas
from datetime import datetime
from zalo_notifier import ZaloNotifier
from telegram_notifier import TelegramNotifier
from voice_notifier import VoiceNotifier
from talkback_streamer import TalkbackStreamer

# ONVIF WSDL PATH
import onvif
from onvif import ONVIFCamera

import socket

import re

# Giới hạn số luồng CPU của OpenCV và OpenMP tránh ngốn 100% CPU
cv2.setNumThreads(2)
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"

ONVIF_WSDL_DIR = os.path.join(os.path.dirname(onvif.__file__), 'wsdl')
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "fflags;nobuffer|flags;low_delay|rtsp_transport;tcp|analyzeduration;0|probesize;32|stimeout;2000000|timeout;2000000"


def extract_ip_port_from_url(url):
    """ Tách Host/IP và Port từ chuỗi URL RTSP """
    m = re.search(r'@([^:/]+)(?::(\d+))?', url)
    if m:
        host = m.group(1)
        port = int(m.group(2)) if m.group(2) else 554
        return host, port
    m2 = re.search(r'rtsp://([^:/]+)(?::(\d+))?', url)
    if m2:
        host = m2.group(1)
        port = int(m2.group(2)) if m2.group(2) else 554
        return host, port
    return None, None


class EfficientCameraEngine:
    """ Luồng đọc Camera tiết kiệm tài nguyên CPU tuyệt đối & Tự động kết nối lại thông minh (Auto-Reconnect) """
    def __init__(self, source):
        self.source = source
        self.cap = None
        self.frame = None
        self.ret = False
        self.is_running = False
        self.lock = threading.Lock()
        self.thread = None

    def _is_network_reachable(self):
        """ Kiểm tra xem camera RTSP IP đã bật nguồn và thông mạng chưa trước khi khởi động OpenCV """
        host, port = extract_ip_port_from_url(str(self.source))
        if not host:
            return True
        try:
            with socket.create_connection((host, port), timeout=0.6):
                return True
        except OSError:
            return False

    def _init_camera(self):
        try:
            src_str = str(self.source).strip()
            if src_str.isdigit():
                # Webcam USB
                cap = cv2.VideoCapture(int(src_str), cv2.CAP_DSHOW)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            else:
                # RTSP Stream
                cap = cv2.VideoCapture(src_str, cv2.CAP_FFMPEG)
            if cap:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap = cap
        except Exception:
            self.cap = None

    def start(self):
        if self.is_running:
            return self
        self.is_running = True
        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()
        return self

    def _update_loop(self):
        last_reconnect_time = 0
        try:
            while self.is_running:
                # 1. Nếu chưa có camera hoặc camera chưa mở được
                if not self.cap or not self.cap.isOpened():
                    now = time.time()
                    if now - last_reconnect_time > 2.0:
                        last_reconnect_time = now
                        if self.cap is not None:
                            try:
                                self.cap.release()
                            except Exception:
                                pass
                            self.cap = None

                        src_str = str(self.source).strip()
                        # Nếu là RTSP IP camera, kiểm tra socket trước khi gọi OpenCV tránh đơ và rò rỉ socket
                        if not src_str.isdigit():
                            if not self._is_network_reachable():
                                with self.lock:
                                    self.ret = False
                                time.sleep(0.5)
                                continue

                        self._init_camera()

                    time.sleep(0.2)
                    continue

                # 2. Đang kết nối -> Đọc khung hình
                try:
                    ret, frame = self.cap.read()
                    if ret and frame is not None:
                        with self.lock:
                            self.frame = frame
                            self.ret = True
                        time.sleep(0.015)
                    else:
                        with self.lock:
                            self.ret = False
                        # Đọc thất bại (mất tín hiệu / tắt nguồn) -> giải phóng cap ngay lập tức để tái kết nối sạch
                        try:
                            if self.cap:
                                self.cap.release()
                        except Exception:
                            pass
                        self.cap = None
                        last_reconnect_time = time.time()
                        time.sleep(0.4)
                except Exception:
                    with self.lock:
                        self.ret = False
                    if self.cap:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                    self.cap = None
                    time.sleep(0.4)
        finally:
            try:
                if self.cap:
                    self.cap.release()
            except Exception:
                pass
            self.cap = None

    def retrieve_frame(self):
        with self.lock:
            if self.ret and self.frame is not None:
                return True, self.frame.copy()
            return False, None

    def stop(self, timeout=1.5):
        """ Yêu cầu dừng luồng an toàn và giải phóng tài nguyên phần cứng """
        self.is_running = False
        if self.thread and self.thread.is_alive():
            try:
                self.thread.join(timeout=timeout)
            except Exception:
                pass
        with self.lock:
            if self.cap:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None


class TapoPTZController:
    """ Quản lý lệnh xoay camera qua ONVIF (Tự động kết nối lại khi camera bật nguồn) """
    def __init__(self, ip, port, user, password):
        self.ip = ip
        self.port = port
        self.user = user
        self.password = password
        self.mycam = None
        self.ptz_service = None
        self.profile = None
        self.is_connected = False
        self.is_running = True
        self.loop = None
        self.thread = None

    def connect_async(self):
        self.is_running = True
        self.thread = threading.Thread(target=self._connect_supervisor, daemon=True)
        self.thread.start()

    def _connect_supervisor(self):
        """ Vòng lặp giám sát: Tự động kết nối ONVIF khi camera bật nguồn hoặc tái kết nối """
        while self.is_running and not self.is_connected:
            try:
                with socket.create_connection((self.ip, int(self.port)), timeout=0.8):
                    pass
                # Cổng ONVIF đã sẵn sàng -> tiến hành bắt tay
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
                self.loop.run_until_complete(self._async_init())
                self.is_connected = True
                print(f"[ONVIF PTZ] Đã kết nối thành công tới Tapo C200 ({self.ip}:{self.port})!")
                self.loop.run_forever()
                break
            except Exception:
                self.is_connected = False
                time.sleep(2.5)

    async def _async_init(self):
        try:
            self.mycam = ONVIFCamera(self.ip, self.port, self.user, self.password, wsdl_dir=ONVIF_WSDL_DIR)
        except Exception:
            self.mycam = ONVIFCamera(self.ip, self.port, self.user, self.password)

        await self.mycam.update_xaddrs()
        self.ptz_service = await self.mycam.create_ptz_service()
        media_service = await self.mycam.create_media_service()
        profiles = await media_service.GetProfiles()
        self.profile = profiles[0]

    def move(self, x_speed, y_speed, timeout=0.4):
        if not self.is_connected or not self.loop:
            return
        asyncio.run_coroutine_threadsafe(self._async_move(x_speed, y_speed, timeout), self.loop)

    async def _async_move(self, x_speed, y_speed, timeout):
        try:
            if not self.ptz_service or not self.profile:
                return
            request = self.ptz_service.create_type('ContinuousMove')
            token = getattr(self.profile, 'token', None)
            request.ProfileToken = token
            request.Velocity = {'PanTilt': {'x': x_speed, 'y': y_speed}}
            await self.ptz_service.ContinuousMove(request)
            await asyncio.sleep(timeout)
            await self.ptz_service.Stop({'ProfileToken': token})
        except Exception:
            pass

    def close(self):
        self.is_running = False
        if self.loop and self.loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._async_close(), self.loop)
            except Exception:
                pass
        self.is_connected = False

    async def _async_close(self):
        if self.mycam:
            try:
                await self.mycam.close()
            except Exception:
                pass
        if self.loop:
            self.loop.stop()


class SmartEHSManagementApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🛡️ SMARTEHS WORKFORCE GUARD - HỆ THỐNG AN TOÀN LAO ĐỘNG & ĐIỂM DANH THÔNG MINH")
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        win_w = min(1420, max(1080, sw - 30))
        win_h = min(820, max(680, sh - 60))
        self.root.geometry(f"{win_w}x{win_h}+15+15")
        self.root.minsize(1050, 640)
        self.root.configure(bg="#0b1329")

        # 1. Config & CSDL
        self.config_mgr = ConfigManager()
        self.db = AttendanceDatabase()

        # Lấy địa chỉ IP mạng nội bộ (LAN)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            self.local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            self.local_ip = "127.0.0.1"

        self.zalo_notifier = ZaloNotifier(self.config_mgr, local_ip=self.local_ip)
        self.telegram_notifier = TelegramNotifier(self.config_mgr)
        self.voice_notifier = VoiceNotifier(self.config_mgr)
        self.talkback = TalkbackStreamer()

        # Quản lý Camera & Zoom
        self.selected_cam_id = None
        self.zoomed_cam_id = None
        self.cam_engines = {}   # {cam_id: EfficientCameraEngine}
        self.cam_views = {}     # {cam_id: {...widgets...}}
        self.cam_grid_dims = (2, 1)


        
        self.ppe_engine = PyTorchGPUEngine("best.pt" if os.path.exists("best.pt") else "models/best.pt")
        self.face_engine = InsightFaceEngine(faces_dir="faces")

        if not os.path.exists("violations"):
            os.makedirs("violations")
        if not os.path.exists("strangers"):
            os.makedirs("strangers")

        # Quản lý Cooldown
        self.cooldown_sec = 30
        self.last_violation_time = {}   # {name: timestamp}
        self.last_attendance_time = {}  # {name: timestamp}
        self.last_stranger_time = {}    # {entity_key: timestamp}
        self.active_workers = {}        # {name: timestamp_checkin}
        self.ptz_controller = None

        # 2. Async Workers: Nhận diện khuôn mặt & Quét AI PPE chạy luồng ngầm (Không giật lag GUI)
        self.face_lock = threading.Lock()
        self.face_engine_lock = threading.Lock()
        self.latest_face_frames = {}         # {cid: frame}
        self.cached_face_results = {}        # {cid: list_of_face_results}

        self.ppe_lock = threading.Lock()
        self.latest_ppe_frames = {}          # {cid: frame}
        self.cached_ppe_objects = {}         # {cid: list_of_objects}
        self.cached_ppe_viols = {}           # {cid: list_of_viols}
        self.last_ppe_scan_timestamp = {}    # {cid: timestamp}

        self.is_running = True
        self.frame_counter = 0

        self.face_thread = threading.Thread(target=self._async_face_worker, daemon=True)
        self.face_thread.start()

        self.ppe_thread = threading.Thread(target=self._async_ppe_worker, daemon=True)
        self.ppe_thread.start()

        self.prev_time = time.time()
        self.fps = 0.0

        # 3. Tải danh sách camera và Khởi dựng giao diện tức thì
        self.cameras = self.config_mgr.get_cameras()
        if not self.cameras:
            self.cameras = [
                {"id": "cam1", "name": "CAM 1 - Cổng Kiểm Soát", "type": "webcam", "source": 0, "role": "attendance"}
            ]

        self._build_ui()
        self._rebuild_camera_grid()
        try:
            self.root.update()  # Vẽ cửa sổ giao diện ngay lập tức để Windows không báo Not Responding
        except Exception:
            pass

        # 4. Khởi động các Camera theo cấu hình Đa Kênh
        self.reload_config_and_restart_cameras()

        # 5. Bắt đầu vòng lặp video & cards
        self.update_video_feed()
        self.refresh_violation_cards()

    def reload_config_and_restart_cameras(self):
        s = self.config_mgr.settings
        self.ppe_conf = s["thresholds"].get("ppe_confidence", 0.45)
        self.face_sim = s["thresholds"].get("face_similarity", 0.50)
        self.cooldown_sec = s["thresholds"].get("cooldown_seconds", 30)
        self.ppe_enabled = s.get("ppe_enabled", {})
        
        self.bgr_pass = self.config_mgr.hex_to_bgr(s["colors"].get("pass", "#00FF00"))
        self.bgr_viol = self.config_mgr.hex_to_bgr(s["colors"].get("violation", "#FF0000"))

        # Kiểm tra trạng thái nút Báo người lạ
        is_voice_en = s.get("voice", {}).get("stranger_enabled", s.get("voice", {}).get("enabled", True))
        v_text = "🔊 BÁO NGƯỜI LẠ: BẬT" if is_voice_en else "🔇 BÁO NGƯỜI LẠ: TẮT"
        v_fg = "#fbbf24" if is_voice_en else "#94a3b8"
        if hasattr(self, 'btn_voice_toggle'):
            self.btn_voice_toggle.config(text=v_text, fg=v_fg)

        # Đọc danh sách camera mới
        new_cameras = self.config_mgr.get_cameras()
        if not new_cameras:
            new_cameras = [
                {"id": "cam1", "name": "CAM 1 - Cổng Kiểm Soát", "type": "webcam", "source": 0, "role": "attendance"}
            ]

        # Kiểm tra xem danh sách camera / nguồn kết nối có thực sự thay đổi không
        old_sources = {c.get("id"): (str(c.get("source")), c.get("role"), c.get("type")) for c in getattr(self, 'cameras', [])}
        new_sources = {c.get("id"): (str(c.get("source")), c.get("role"), c.get("type")) for c in new_cameras}
        cameras_changed = (old_sources != new_sources)
        self.cameras = new_cameras

        if not cameras_changed and len(self.cam_engines) == len(new_cameras):
            if hasattr(self, 'lbl_talk_status'):
                self.lbl_talk_status.config(text="✅ Đã cập nhật cấu hình hệ thống tức thì!", fg="#34d399")
            return

        # Khởi động lại an toàn trong worker thread
        if hasattr(self, 'lbl_talk_status'):
            self.lbl_talk_status.config(text="⏳ Đang kết nối luồng camera...", fg="#fbbf24")

        def restart_worker():
            for eng in list(self.cam_engines.values()):
                try:
                    eng.stop(timeout=0.6)
                except Exception:
                    pass
            self.cam_engines.clear()
            time.sleep(0.1)

            new_engines = {}
            for cam_cfg in self.cameras:
                c_id = cam_cfg.get("id")
                c_src = cam_cfg.get("source", 0)
                new_engines[c_id] = EfficientCameraEngine(c_src).start()
            self.cam_engines = new_engines

            if self.ptz_controller:
                try:
                    self.ptz_controller.close()
                except Exception:
                    pass
                self.ptz_controller = None

            tapo_cam = next((c for c in self.cameras if c.get("type") == "tapo" or "tapo" in str(c.get("name", "")).lower()), None)
            if tapo_cam and tapo_cam.get("tapo_ip"):
                self.ptz_controller = TapoPTZController(
                    tapo_cam['tapo_ip'],
                    tapo_cam.get('tapo_onvif_port', 2020),
                    tapo_cam.get('tapo_user', ''),
                    tapo_cam.get('tapo_pass', '')
                )
                self.ptz_controller.connect_async()

            def on_complete():
                if hasattr(self, 'lbl_talk_status'):
                    self.lbl_talk_status.config(text="✅ Đã kết nối camera thành công!", fg="#34d399")

            try:
                self.root.after_idle(on_complete)
            except Exception:
                pass

        threading.Thread(target=restart_worker, daemon=True).start()

    def _rebuild_camera_grid(self):
        """ Tự động bố trí lưới hiển thị camera hợp lý theo số lượng (Dynamic Grid Layout) """
        for widget in self.video_panel.winfo_children():
            widget.destroy()
        self.cam_views.clear()
        self.zoomed_cam_id = None

        n = len(self.cameras)
        if n <= 1:
            rows, cols = 1, 1
        elif n == 2:
            rows, cols = 1, 2   # 1 hàng 2 cột: side-by-side ngang chuẩn màn hình
        elif n in [3, 4]:
            rows, cols = 2, 2   # Lưới 2x2
        elif n in [5, 6]:
            rows, cols = 2, 3   # Lưới 3x2 (3 cột x 2 hàng = 6 ô)
        elif n in [7, 8, 9]:
            rows, cols = 3, 3   # Lưới 3x3 (3 cột x 3 hàng = 9 ô)
        elif n in [10, 11, 12]:
            rows, cols = 3, 4   # Lưới 4x3 (4 cột x 3 hàng = 12 ô)
        elif n in [13, 14, 15, 16]:
            rows, cols = 4, 4   # Lưới 4x4
        else:
            cols = 4
            rows = (n + 3) // 4

        self.cam_grid_dims = (rows, cols)

        # Reset toàn bộ weights của các hàng và cột cũ để tránh giữ lại các hàng/cột ma (ghost rows/columns)
        for r in range(16):
            self.video_panel.rowconfigure(r, weight=0, uniform="")
        for c in range(16):
            self.video_panel.columnconfigure(c, weight=0, uniform="")

        for r in range(rows):
            self.video_panel.rowconfigure(r, weight=1, uniform="cam_row")
        for c in range(cols):
            self.video_panel.columnconfigure(c, weight=1, uniform="cam_col")

        for idx, cam_cfg in enumerate(self.cameras):
            cam_id = cam_cfg.get("id", f"cam_{idx+1}")
            if n == 3 and idx == 2:
                # Camera thứ 3 trải dài toàn bộ hàng 2 (columnspan=2), lấp kín màn hình cân đối 100%
                r = 1
                c = 0
                colspan = 2
            else:
                r = idx // cols
                c = idx % cols
                colspan = 1

            # Container Frame với viền bo công nghệ
            f_cam = tk.Frame(self.video_panel, bg="#111c38", bd=2, relief=tk.SOLID,
                             highlightthickness=2, highlightbackground="#1e293b", highlightcolor="#38bdf8")
            f_cam.grid(row=r, column=c, rowspan=1, columnspan=colspan, sticky="nsew", padx=3, pady=3)

            # Header Bar
            h_cam = tk.Frame(f_cam, bg="#1e293b", height=28)
            h_cam.pack(side=tk.TOP, fill=tk.X)
            h_cam.pack_propagate(False)

            role = cam_cfg.get("role", "ppe")
            role_icon = "📹" if role == "attendance" else "🏗️"
            role_fg = "#38bdf8" if role == "attendance" else "#60a5fa"

            lbl_title = tk.Label(h_cam, text=f"{role_icon} {cam_cfg.get('name', 'Camera')}",
                                 font=("Segoe UI", 9, "bold"), bg="#1e293b", fg=role_fg)
            lbl_title.pack(side=tk.LEFT, padx=8)

            lbl_badge = tk.Label(h_cam, text="ĐANG KẾT NỐI... 🟡", font=("Segoe UI", 8, "bold"), bg="#1e293b", fg="#fbbf24")
            lbl_badge.pack(side=tk.RIGHT, padx=6)

            lbl_talk_badge = tk.Label(h_cam, text="", font=("Segoe UI", 8, "bold"), bg="#1e293b", fg="#f59e0b")
            lbl_talk_badge.pack(side=tk.RIGHT, padx=4)

            # Video Canvas Box
            box_frame = tk.Frame(f_cam, bg="#050a17")
            box_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            box_frame.pack_propagate(False)

            lbl_video = tk.Label(box_frame, bg="#050a17", text="Đang nạp luồng camera...", fg="#64748b")
            lbl_video.pack(fill=tk.BOTH, expand=True)

            self.cam_views[cam_id] = {
                "cfg": cam_cfg,
                "frame": f_cam,
                "header": h_cam,
                "lbl_title": lbl_title,
                "lbl_badge": lbl_badge,
                "lbl_talk_badge": lbl_talk_badge,
                "box": box_frame,
                "lbl_video": lbl_video,
                "row": r,
                "col": c,
                "rowspan": 1,
                "colspan": colspan
            }

            # Đăng ký sự kiện: 1 Click = Phóng to & Chọn; Double-Click = Thu nhỏ lưới
            for w in [f_cam, h_cam, lbl_title, lbl_badge, lbl_talk_badge, box_frame, lbl_video]:
                w.bind("<Button-1>", lambda event, cid=cam_id: self.on_cam_clicked(cid))
                w.bind("<Double-Button-1>", lambda event, cid=cam_id: self.on_cam_double_clicked(cid))

        self.root.update_idletasks()

        # Ưu tiên chọn Camera TAPO để sẵn sàng đàm thoại phát loa
        tapo_id = None
        for c in self.cameras:
            if c.get("type") == "tapo" or "tapo" in str(c.get("name", "")).lower():
                tapo_id = c.get("id")
                break
        target_id = self.selected_cam_id or tapo_id or (self.cameras[0].get("id") if self.cameras else None)
        if target_id:
            self.select_camera_for_talk(target_id)

        # Cập nhật danh sách camera vào combobox đàm thoại
        if hasattr(self, 'cb_target_talk_cam'):
            cam_items = [f"{c.get('name', 'Camera')}" for c in self.cameras]
            self.cb_target_talk_cam['values'] = cam_items

    def on_cam_clicked(self, cam_id):
        """ Nhấn 1 lần: Chọn camera để đàm thoại âm thanh (Không bị nhảy phóng to) """
        self.select_camera_for_talk(cam_id)

    def on_cam_double_clicked(self, cam_id):
        """ Nhấn đúp: Phóng to 100% hoặc Thu nhỏ camera về lưới bình thường """
        if self.zoomed_cam_id == cam_id:
            self.restore_camera_grid()
        else:
            self.zoom_camera(cam_id)

    def zoom_camera(self, cam_id):
        """ Phóng to 1 Camera chiếm 100% diện tích màn hình xem """
        if cam_id not in self.cam_views:
            return
        self.zoomed_cam_id = cam_id
        rows, cols = self.cam_grid_dims

        for cid, v in self.cam_views.items():
            if cid == cam_id:
                v["frame"].grid(row=0, column=0, rowspan=rows, columnspan=cols, sticky="nsew", padx=1, pady=1)
                v["lbl_talk_badge"].config(text="🔍 [ĐANG PHÓNG TO - NHẤN ĐÚP ĐỂ THU NHỎ]")
            else:
                v["frame"].grid_remove()

        self.root.update_idletasks()

    def restore_camera_grid(self):
        """ Thu nhỏ camera quay về bố cục lưới ban đầu """
        self.zoomed_cam_id = None
        for cid, v in self.cam_views.items():
            v["frame"].grid(
                row=v["row"],
                column=v["col"],
                rowspan=v.get("rowspan", 1),
                columnspan=v.get("colspan", 1),
                sticky="nsew",
                padx=3,
                pady=3
            )
            if cid == self.selected_cam_id:
                v["lbl_talk_badge"].config(text="🎯 [ĐANG CHỌN ĐÀM THOẠI 🎙️]")
            else:
                v["lbl_talk_badge"].config(text="")

        self.root.update_idletasks()

    def select_camera_for_talk(self, cam_id):
        """ Đánh dấu Camera được chọn để đàm thoại / giao tiếp âm thanh """
        self.selected_cam_id = cam_id
        for cid, v in self.cam_views.items():
            if cid == cam_id:
                v["frame"].config(highlightbackground="#f59e0b", highlightthickness=2)
                if self.zoomed_cam_id != cam_id:
                    v["lbl_talk_badge"].config(text="🎯 [ĐANG CHỌN ĐÀM THOẠI 🎙️]")
                cam_name = v["cfg"].get("name", "Camera")
                if hasattr(self, 'lbl_target_talk_cam'):
                    self.lbl_target_talk_cam.config(text=f"🎯 ĐÍCH PHÁT: {cam_name[:32]}")
                if hasattr(self, 'cb_target_talk_cam'):
                    for idx, c in enumerate(self.cameras):
                        if c.get("id") == cid:
                            try:
                                self.cb_target_talk_cam.current(idx)
                            except Exception:
                                pass
                            break
                if hasattr(self, 'btn_live_talk') and not getattr(self.talkback, 'is_talking', False):
                    self.btn_live_talk.config(text="🎙️ BẬT NÓI TRỰC TIẾP (LIVE MIC)")
            else:
                v["frame"].config(highlightbackground="#1e293b", highlightthickness=1)
                if self.zoomed_cam_id != cid:
                    v["lbl_talk_badge"].config(text="")

    def _on_talk_cam_dropdown(self, event=None):
        if not hasattr(self, 'cb_target_talk_cam'):
            return
        idx = self.cb_target_talk_cam.current()
        if 0 <= idx < len(self.cameras):
            target_cid = self.cameras[idx].get("id")
            self.select_camera_for_talk(target_cid)

    def _on_volume_slider_changed(self, val):
        """ Xử lý khi người dùng kéo thanh chỉnh cường độ thông báo / loa Tapo """
        try:
            v = int(float(val))
            if hasattr(self, 'lbl_volume_val'):
                self.lbl_volume_val.config(text=f"🔊 CƯỜNG ĐỘ LOA TAPO: {v}%")
            cur_view = self.cam_views.get(self.selected_cam_id)
            cur_cam_cfg = cur_view["cfg"] if cur_view else {}
            if hasattr(self, 'talkback'):
                self.talkback.set_tapo_volume(cur_cam_cfg, v)
        except Exception:
            pass

    def on_hold_talk_press(self, event=None):
        """ Bấm giữ chuột để nói chuyện (Giống tính năng Nói chuyện trong App Tapo trên điện thoại) """
        cur_view = self.cam_views.get(self.selected_cam_id)
        cur_cam_cfg = dict(cur_view["cfg"]) if cur_view else {}

        if cur_cam_cfg.get("type") != "tapo" and "tapo" not in str(cur_cam_cfg.get("name", "")).lower():
            tapo_cfg = next((c for c in self.cameras if c.get("type") == "tapo" or "tapo" in str(c.get("name", "")).lower()), None)
            if tapo_cfg:
                for k, v in tapo_cfg.items():
                    if k not in cur_cam_cfg:
                        cur_cam_cfg[k] = v

        vol = int(self.slider_volume.get()) if hasattr(self, 'slider_volume') else 80
        start_fn = getattr(self.talkback, 'start_hold_to_talk', None) or getattr(self.talkback, 'start_live_talk', None)
        success = False
        if callable(start_fn):
            success = start_fn(
                cur_cam_cfg,
                volume=vol,
                on_volume_cb=self._on_talk_volume,
                on_status_cb=self._on_talk_status
            )
        if success and hasattr(self, 'btn_hold_talk'):
            self.btn_hold_talk.config(
                text="🔴 ĐANG NÓI... (THẢ ĐỂ DỪNG)",
                bg="#dc2626",
                activebackground="#b91c1c"
            )

    def on_hold_talk_release(self, event=None):
        """ Thả chuột ra là ngắt thu âm và truyền giọng nói tức thì sang Loa Camera Tapo """
        def on_finish():
            if hasattr(self, 'btn_hold_talk'):
                self.btn_hold_talk.config(
                    text="🎙️ GIỮ ĐỂ NÓI CHUYỆN (HOLD TO TALK)",
                    bg="#059669",
                    activebackground="#047857"
                )
            if hasattr(self, 'vol_bar'):
                self.vol_bar['value'] = 0
        stop_fn = getattr(self.talkback, 'stop_hold_to_talk', None) or getattr(self.talkback, 'stop_live_talk', None)
        if callable(stop_fn):
            stop_fn(on_finish_cb=on_finish)
        on_finish()

    def toggle_live_talk(self):
        """
        NÓI TRỰC TIẾP VÀO TAPO / LOA HIỆN TRƯỜNG QUA MIC MÁY CHỦ (LAPTOP):
        - Bấm 1 lần: Bật đàm thoại trực tiếp (Live Mic).
        - Bấm lần nữa: Dừng đàm thoại.
        - Không cần qua bước thu âm tệp WAV và bấm phát lại.
        """
        cur_view = self.cam_views.get(self.selected_cam_id)
        cur_cam_cfg = dict(cur_view["cfg"]) if cur_view else {}

        # Nếu đang chọn webcam, tự động đính kèm cấu hình Tapo để phát loa Tapo song song
        if cur_cam_cfg.get("type") != "tapo" and "tapo" not in str(cur_cam_cfg.get("name", "")).lower():
            tapo_cfg = next((c for c in self.cameras if c.get("type") == "tapo" or "tapo" in str(c.get("name", "")).lower()), None)
            if tapo_cfg:
                for k, v in tapo_cfg.items():
                    if k not in cur_cam_cfg:
                        cur_cam_cfg[k] = v

        vol = int(self.slider_volume.get()) if hasattr(self, 'slider_volume') else 80

        if not getattr(self.talkback, 'is_talking', False):
            success = self.talkback.start_live_talk(
                cur_cam_cfg,
                volume=vol,
                on_volume_cb=self._on_talk_volume,
                on_status_cb=self._on_talk_status
            )
            if success:
                self.btn_live_talk.config(
                    text="🔴 ĐANG NÓI TRỰC TIẾP (BẤM ĐỂ TẮT)",
                    bg="#dc2626",
                    activebackground="#b91c1c"
                )
        else:
            def on_finish():
                self.btn_live_talk.config(
                    text="🎙️ BẬT NÓI TRỰC TIẾP (LIVE MIC)",
                    bg="#0284c7",
                    activebackground="#0369a1"
                )
                if hasattr(self, 'vol_bar'):
                    self.vol_bar['value'] = 0
            self.talkback.stop_live_talk(on_finish_cb=on_finish)
            on_finish()

    def action_test_tapo_speaker(self):
        """ Kích hoạt phát thử Loa/Còi Camera Tapo theo cường độ âm lượng đã chỉnh """
        cur_view = self.cam_views.get(self.selected_cam_id)
        cur_cam_cfg = dict(cur_view["cfg"]) if cur_view else {}

        # Tự động tìm cấu hình Camera Tapo để thử loa ngay cả khi đang chọn camera khác
        if cur_cam_cfg.get("type") != "tapo" and "tapo" not in str(cur_cam_cfg.get("name", "")).lower():
            tapo_cfg = next((c for c in self.cameras if c.get("type") == "tapo" or "tapo" in str(c.get("name", "")).lower()), None)
            if tapo_cfg:
                cur_cam_cfg = dict(tapo_cfg)

        vol = int(self.slider_volume.get()) if hasattr(self, 'slider_volume') else 80

        self.btn_test_speaker.config(state=tk.DISABLED, bg="#475569")
        if hasattr(self, 'lbl_talk_status'):
            self.lbl_talk_status.config(text=f"⏳ Đang kết nối loa Tapo (Cường độ {vol}%)...", fg="#fbbf24")

        def _worker():
            ok, msg = self.talkback.test_tapo_speaker(cur_cam_cfg, volume=vol)
            def _done():
                self.btn_test_speaker.config(state=tk.NORMAL, bg="#1e293b")
                if ok:
                    if hasattr(self, 'lbl_talk_status'):
                        self.lbl_talk_status.config(text=msg[:75], fg="#34d399")
                else:
                    if hasattr(self, 'lbl_talk_status'):
                        self.lbl_talk_status.config(text="⚠️ Mật khẩu App Tapo chưa khớp (Nhấn để sửa)", fg="#f87171")
                    messagebox.showwarning("CẦN CẬP NHẬT MẬT KHẨU APP TAPO", msg)
            self.root.after_idle(_done)
        threading.Thread(target=_worker, daemon=True).start()

    def toggle_talkback(self):
        """ Alias tương thích ngược: gọi toggle_live_talk """
        self.toggle_live_talk()

    def replay_talkback(self):
        """ Phát lại tệp âm thanh vừa thu gần nhất ra Loa Camera Tapo """
        if getattr(self.talkback, 'is_talking', False) or getattr(self.talkback, 'is_broadcasting', False):
            return

        cur_view = self.cam_views.get(self.selected_cam_id)
        cur_cam_cfg = cur_view["cfg"] if cur_view else {}

        ok = self.talkback.broadcast_last_audio(cur_cam_cfg)
        if not ok and hasattr(self, 'lbl_talk_status'):
            self.lbl_talk_status.config(text="⚠️ Chưa có đoạn thu âm nào trước đó.", fg="#fbbf24")

    def _update_record_timer(self):
        if hasattr(self, 'talkback') and getattr(self.talkback, 'is_recording', False):
            elapsed = int(time.time() - getattr(self, 'talk_record_start', time.time()))
            mm = elapsed // 60
            ss = elapsed % 60
            self.btn_talkback.config(text=f"⏹️ DỪNG THU & PHÁT RA CAMERA ({mm:02d}:{ss:02d})")
            self.root.after(500, self._update_record_timer)

    def _on_talk_volume(self, volume):
        try:
            val = int(volume * 100)
            self.root.after_idle(lambda: self.vol_bar.config(value=val))
        except Exception:
            pass

    def _on_talk_status(self, msg):
        if hasattr(self, 'lbl_talk_status'):
            fg = "#38bdf8"
            if "⚠️" in msg or "Lỗi" in msg or "từ chối" in msg or "401" in msg:
                fg = "#f87171"
            elif "ĐÃ PHÁT" in msg or "🔊" in msg or "✅" in msg:
                fg = "#34d399"
            self.root.after_idle(lambda: self.lbl_talk_status.config(text=msg, fg=fg))

    def open_settings_dialog(self):
        SettingsDialog(self.root, self.config_mgr, on_save_callback=self.reload_config_and_restart_cameras)

    def get_latest_frame_for_capture(self, preferred_cam_id=None):
        """ Trích xuất khung hình mới nhất phục vụ chụp ảnh đăng ký khuôn mặt mà không làm gián đoạn luồng camera """
        if preferred_cam_id and preferred_cam_id in self.cam_engines:
            ret, frame = self.cam_engines[preferred_cam_id].retrieve_frame()
            if ret and frame is not None:
                return True, frame

        if "cam1" in self.cam_engines:
            ret, frame = self.cam_engines["cam1"].retrieve_frame()
            if ret and frame is not None:
                return True, frame

        for cid, eng in self.cam_engines.items():
            ret, frame = eng.retrieve_frame()
            if ret and frame is not None:
                return True, frame

        return False, None

    def open_employee_manager_dialog(self):
        EmployeeManagerDialog(
            self.root, 
            self.db, 
            face_engine_callback=self.reload_face_database,
            get_frame_callback=self.get_latest_frame_for_capture
        )

    def action_export_excel(self):
        try:
            from tkinter import filedialog
            default_name = f"Bao_Cao_PPE_Diem_Danh_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            filepath = filedialog.asksaveasfilename(
                title="Lưu Báo Cáo Excel",
                initialfile=default_name,
                defaultextension=".xlsx",
                filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")]
            )
            if not filepath:
                return
            ok, res = self.db.export_to_excel(filepath)
            if ok:
                messagebox.showinfo("Xuất Báo Cáo", f"Đã xuất báo cáo Excel thành công tại:\n{res}")
            else:
                messagebox.showerror("Lỗi", f"Không thể xuất báo cáo Excel:\n{res}")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Đã xảy ra lỗi khi xuất Excel:\n{e}")

    def reload_face_database(self):
        self.face_engine.load_known_faces()

    def _async_face_worker(self):
        """ Luồng InsightFace bất đồng bộ xử lý độc lập cho từng camera điểm danh """
        while self.is_running:
            target_cid = None
            frame_to_process = None
            with self.face_lock:
                for c_id, f in list(self.latest_face_frames.items()):
                    if f is not None:
                        target_cid = c_id
                        frame_to_process = f
                        self.latest_face_frames[c_id] = None
                        break

            if target_cid and frame_to_process is not None:
                # Tối ưu kích thước khuôn mặt: nếu frame > 800px, thu nhỏ nhẹ để nhận diện siêu nhanh
                fh, fw = frame_to_process.shape[:2]
                if fw > 800:
                    scale = 800.0 / fw
                    small_frame = cv2.resize(frame_to_process, (800, int(fh * scale)), interpolation=cv2.INTER_LINEAR)
                    with self.face_engine_lock:
                        raw_results = self.face_engine.recognize_faces(small_frame, threshold=self.face_sim)
                    inv_scale = 1.0 / scale
                    results = []
                    for r in raw_results:
                        bbox_val = r.get('bbox')
                        if isinstance(bbox_val, (list, tuple, np.ndarray)) and len(bbox_val) >= 4:
                            r['bbox'] = [
                                float(bbox_val[0]) * inv_scale,
                                float(bbox_val[1]) * inv_scale,
                                float(bbox_val[2]) * inv_scale,
                                float(bbox_val[3]) * inv_scale
                            ]
                        results.append(r)
                else:
                    with self.face_engine_lock:
                        results = self.face_engine.recognize_faces(frame_to_process, threshold=self.face_sim)

                with self.face_lock:
                    self.cached_face_results[target_cid] = results
                time.sleep(0.08)
            else:
                time.sleep(0.04)

    def _async_ppe_worker(self):
        """ Luồng suy luận YOLO PPE & Xử lý vi phạm hoàn toàn bất đồng bộ - Giải phóng 100% tài nguyên GUI """
        while self.is_running:
            cid = None
            frame_to_process = None
            cam_name = "Hiện trường"
            with self.ppe_lock:
                for c_id, f in list(self.latest_ppe_frames.items()):
                    if f is not None:
                        cid = c_id
                        frame_to_process = f
                        self.latest_ppe_frames[c_id] = None
                        for c_cfg in self.cameras:
                            if c_cfg.get("id") == cid:
                                cam_name = c_cfg.get("name", "Hiện trường")
                                break
                        break

            if cid and frame_to_process is not None:
                try:
                    self._execute_ppe_inference(cid, frame_to_process, cam_name)
                except Exception as e:
                    print(f"Lỗi suy luận PPE async ({cid}): {e}")
                time.sleep(0.06)
            else:
                time.sleep(0.03)

    def _execute_ppe_inference(self, cid, frame, cam_name):
        curr_time = time.time()
        frame_h, frame_w = frame.shape[:2]

        # Tối ưu kích thước đầu vào cho YOLO: thu nhỏ nhẹ nếu frame > 960px để tăng tốc gấp đôi
        if frame_w > 960:
            scale = 960.0 / frame_w
            infer_frame = cv2.resize(frame, (960, int(frame_h * scale)), interpolation=cv2.INTER_LINEAR)
            inv_scale = 1.0 / scale
        else:
            infer_frame = frame
            inv_scale = 1.0

        res_list = list(self.ppe_engine.infer(infer_frame, conf=self.ppe_conf))
        first_res = res_list[0] if res_list else None
        ppe_boxes = getattr(first_res, 'boxes', None)

        cached_objects = []
        cached_viols = []
        person_boxes = []
        ppe_items = []

        if ppe_boxes is not None and first_res is not None:
            names_dict = getattr(first_res, 'names', {})
            for box, cls_id in zip(ppe_boxes.xyxy.cpu().numpy(), ppe_boxes.cls.cpu().numpy()):
                orig_box = [box[0] * inv_scale, box[1] * inv_scale, box[2] * inv_scale, box[3] * inv_scale]
                cname = str(names_dict.get(int(cls_id), "")).lower().strip()
                if cname == "person":
                    person_boxes.append(orig_box)
                else:
                    ppe_items.append({"box": orig_box, "name": cname})
                    cached_objects.append({"box": orig_box, "name": cname})

        for p_idx, pbox in enumerate(person_boxes):
            px1, py1, px2, py2 = [int(v) for v in pbox]
            worker_viols = []
            for obj in ppe_items:
                ox1, oy1, ox2, oy2 = [float(v) for v in obj["box"]]
                ocx = (ox1 + ox2) / 2.0
                ocy = (oy1 + oy2) / 2.0
                if (px1 - 25 <= ocx <= px2 + 25) and (py1 - 25 <= ocy <= py2 + 25):
                    obj_name = obj["name"]
                    if self.ppe_enabled.get("helmet", True) and any(k in obj_name for k in ['no-helmet', 'no_helmet', 'no-hardhat', 'no helmet', 'no hardhat']):
                        if "Thiếu mũ" not in worker_viols: worker_viols.append("Thiếu mũ")
                    if self.ppe_enabled.get("vest", True) and any(k in obj_name for k in ['no-vest', 'no_vest', 'no-safety-vest', 'no vest', 'no safety vest']):
                        if "Thiếu áo" not in worker_viols: worker_viols.append("Thiếu áo")
                    if self.ppe_enabled.get("gloves", False) and any(k in obj_name for k in ['no-gloves', 'no_gloves', 'no gloves']):
                        if "Thiếu găng tay" not in worker_viols: worker_viols.append("Thiếu găng tay")
                    if self.ppe_enabled.get("glasses", False) and any(k in obj_name for k in ['no-glasses', 'no_glasses', 'no glasses']):
                        if "Thiếu kính" not in worker_viols: worker_viols.append("Thiếu kính")
                    if self.ppe_enabled.get("boots", False) and any(k in obj_name for k in ['no-boots', 'no_boots', 'no boots']):
                        if "Thiếu giày" not in worker_viols: worker_viols.append("Thiếu giày")

            if len(worker_viols) > 0:
                viol_desc = "VI PHẠM: " + ", ".join(worker_viols)
                person_identity = None

                head_y1 = max(0, py1)
                head_y2 = min(frame_h, py1 + int((py2 - py1) * 0.45))
                head_x1 = max(0, px1)
                head_x2 = min(frame_w, px2)
                head_crop = frame[head_y1:head_y2, head_x1:head_x2]

                if head_crop.size > 0 and (head_y2 - head_y1) >= 28 and (head_x2 - head_x1) >= 28:
                    try:
                        with self.face_engine_lock:
                            f_results = self.face_engine.recognize_faces(head_crop, threshold=self.face_sim)
                        if f_results and len(f_results) > 0:
                            f_name = f_results[0]['name']
                            if f_name != "Unknown":
                                person_identity = f_name
                            else:
                                person_identity = "Người lạ"
                    except Exception:
                        pass

                if not person_identity:
                    active_now = [w for w, t in getattr(self, 'active_workers', {}).items() if curr_time - t < 7200]
                    if active_now:
                        person_identity = active_now[p_idx % len(active_now)]
                    elif len(self.face_engine.known_face_names) > 0:
                        person_identity = self.face_engine.known_face_names[p_idx % len(self.face_engine.known_face_names)]
                    else:
                        person_identity = "Người lạ"

                is_stranger = (person_identity == "Người lạ" or "người lạ" in str(person_identity).lower())
                viol_label = "Người lạ" if is_stranger else person_identity
                viol_display_tag = f"⚠️ {viol_desc} ({viol_label})"

                cached_viols.append({
                    "box": pbox,
                    "desc": viol_desc,
                    "idx": p_idx,
                    "name": viol_label,
                    "display": viol_display_tag,
                    "is_stranger": is_stranger
                })

                worker_key = f"{viol_label}_{int((px1+px2)/2 // 150)}"
                last_v_time = self.last_violation_time.get(worker_key, 0)
                if curr_time - last_v_time >= self.cooldown_sec:
                    self.last_violation_time[worker_key] = curr_time
                    ev_path = f"violations/vio_{cid}_{int(curr_time)}_{p_idx}.jpg"
                    pad_y1 = max(0, py1 - 20)
                    pad_y2 = min(frame_h, py2 + 20)
                    pad_x1 = max(0, px1 - 20)
                    pad_x2 = min(frame_w, px2 + 20)
                    ev_img = frame[pad_y1:pad_y2, pad_x1:pad_x2]
                    if ev_img.size > 0:
                        cv2.imwrite(ev_path, ev_img)
                    else:
                        cv2.imwrite(ev_path, frame)

                    self.db.log_violation(viol_label, viol_desc, ev_path, cooldown_seconds=self.cooldown_sec)

                    zalo_name = "🚨 Người lạ chưa đăng ký" if is_stranger else f"Nhân sự {viol_label}"
                    self.zalo_notifier.send_violation_alert(
                        name=zalo_name,
                        violation_type=viol_desc,
                        evidence_path=ev_path,
                        location=cam_name
                    )
                    self.telegram_notifier.send_violation_alert(
                        name=zalo_name,
                        violation_type=viol_desc,
                        evidence_path=ev_path,
                        location=cam_name
                    )
                    threading.Thread(target=self._play_alert_sound, daemon=True).start()

        with self.ppe_lock:
            self.cached_ppe_objects[cid] = cached_objects
            self.cached_ppe_viols[cid] = cached_viols
            self.last_ppe_scan_timestamp[cid] = curr_time

    def _build_ui(self):
        self.root.focus_set()

        # ==========================================
        # 1. TOP HEADER BAR
        # ==========================================
        header = tk.Frame(self.root, bg="#0f172a", height=50)
        header.pack(side=tk.TOP, fill=tk.X)
        header.pack_propagate(False)

        lbl_logo = tk.Label(header, text="🛡️ SMART EHS", font=("Segoe UI", 12, "bold"), bg="#0f172a", fg="#38bdf8")
        lbl_logo.pack(side=tk.LEFT, padx=(15, 5), pady=8)

        lbl_subtitle = tk.Label(header, text="|  HỆ THỐNG GIÁM SÁT AN TOÀN PPE & ĐIỂM DANH ĐA KÊNH",
                                font=("Segoe UI", 10), bg="#0f172a", fg="#94a3b8")
        lbl_subtitle.pack(side=tk.LEFT, pady=8)

        # Trạng thái bên phải Header
        status_box = tk.Frame(header, bg="#0f172a")
        status_box.pack(side=tk.RIGHT, padx=15, pady=8)


        is_voice_en = self.config_mgr.settings.get("voice", {}).get("stranger_enabled", self.config_mgr.settings.get("voice", {}).get("enabled", True))
        v_text = "🔊 BÁO NGƯỜI LẠ: BẬT" if is_voice_en else "🔇 BÁO NGƯỜI LẠ: TẮT"
        v_fg = "#fbbf24" if is_voice_en else "#94a3b8"
        self.btn_voice_toggle = tk.Button(status_box, text=v_text,
                                          font=("Segoe UI", 9, "bold"), bg="#1e293b", fg=v_fg,
                                          activebackground="#334155", bd=0, padx=8, pady=3, cursor="hand2",
                                          command=self.toggle_stranger_voice_alert)
        self.btn_voice_toggle.pack(side=tk.LEFT, padx=4)

        self.lbl_fps_badge = tk.Label(status_box, text="⚡ 0 FPS", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#34d399", padx=8, pady=3)
        self.lbl_fps_badge.pack(side=tk.LEFT, padx=4)

        self.lbl_clock = tk.Label(status_box, text="", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#f1f5f9", padx=8, pady=3)
        self.lbl_clock.pack(side=tk.LEFT, padx=4)

        # ==========================================
        # 2. MAIN WORKSPACE (SPLIT: VIDEO & SIDEBAR)
        # ==========================================
        content_frame = tk.Frame(self.root, bg="#0b1329")
        content_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        # --- A. VIDEO PANEL (LEFT) ---
        self.video_panel = tk.Frame(content_frame, bg="#0b1329")
        self.video_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        # --- B. CONTROL SIDEBAR (RIGHT) ---
        right_panel = tk.Frame(content_frame, bg="#111c38", width=340, bd=1, relief=tk.SOLID)
        right_panel.pack(side=tk.RIGHT, fill=tk.Y)
        right_panel.pack_propagate(False)

        # Thống kê nhanh trong ngày
        stats_frame = tk.Frame(right_panel, bg="#111c38")
        stats_frame.pack(fill=tk.X, padx=10, pady=(10, 6))

        card_att = tk.Frame(stats_frame, bg="#1e293b", bd=1, relief=tk.SOLID)
        card_att.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2))
        tk.Label(card_att, text="ĐIỂM DANH", font=("Segoe UI", 7, "bold"), bg="#1e293b", fg="#94a3b8").pack(pady=(4, 0))
        self.lbl_stat_att = tk.Label(card_att, text="0", font=("Segoe UI", 15, "bold"), bg="#1e293b", fg="#38bdf8")
        self.lbl_stat_att.pack(pady=(0, 4))

        card_vio = tk.Frame(stats_frame, bg="#1e293b", bd=1, relief=tk.SOLID)
        card_vio.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        tk.Label(card_vio, text="VI PHẠM", font=("Segoe UI", 7, "bold"), bg="#1e293b", fg="#94a3b8").pack(pady=(4, 0))
        self.lbl_stat_vio = tk.Label(card_vio, text="0", font=("Segoe UI", 15, "bold"), bg="#1e293b", fg="#f87171")
        self.lbl_stat_vio.pack(pady=(0, 4))

        card_st = tk.Frame(stats_frame, bg="#1e293b", bd=1, relief=tk.SOLID)
        card_st.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(2, 0))
        tk.Label(card_st, text="NGƯỜI LẠ", font=("Segoe UI", 7, "bold"), bg="#1e293b", fg="#94a3b8").pack(pady=(4, 0))
        self.lbl_stat_stranger = tk.Label(card_st, text="0", font=("Segoe UI", 15, "bold"), bg="#1e293b", fg="#fb923c")
        self.lbl_stat_stranger.pack(pady=(0, 4))

        # CỤM ĐÀM THOẠI TRỰC TIẾP & ĐIỀU CHỈNH CƯỜNG ĐỘ LOA TAPO
        talk_box = tk.LabelFrame(right_panel, text="🎙️ ĐÀM THOẠI TRỰC TIẾP & LOA TAPO", font=("Segoe UI", 8, "bold"),
                                 bg="#111c38", fg="#38bdf8", bd=1)
        talk_box.pack(fill=tk.X, padx=10, pady=4)

        f_target = tk.Frame(talk_box, bg="#111c38")
        f_target.pack(fill=tk.X, padx=8, pady=(4, 2))
        tk.Label(f_target, text="🎯 ĐÍCH PHÁT:", font=("Segoe UI", 8, "bold"), bg="#111c38", fg="#f59e0b").pack(side=tk.LEFT)

        cam_items = [f"{c.get('name', 'Camera')}" for c in getattr(self, 'cameras', [])]
        self.cb_target_talk_cam = ttk.Combobox(f_target, values=cam_items, state="readonly", font=("Segoe UI", 8))
        self.cb_target_talk_cam.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        self.cb_target_talk_cam.bind("<<ComboboxSelected>>", self._on_talk_cam_dropdown)

        # Thanh trượt điều chỉnh cường độ âm thanh thông báo / Loa Tapo
        f_vol = tk.Frame(talk_box, bg="#111c38")
        f_vol.pack(fill=tk.X, padx=8, pady=(3, 1))
        self.lbl_volume_val = tk.Label(f_vol, text="🔊 CƯỜNG ĐỘ LOA TAPO: 80%", font=("Segoe UI", 8, "bold"), bg="#111c38", fg="#38bdf8")
        self.lbl_volume_val.pack(side=tk.LEFT)

        self.slider_volume = ttk.Scale(talk_box, from_=10, to=100, orient=tk.HORIZONTAL, value=80, command=self._on_volume_slider_changed)
        self.slider_volume.pack(fill=tk.X, padx=10, pady=(0, 3))

        # Hiển thị mức sóng âm Micro laptop (VU Meter)
        self.vol_bar = ttk.Progressbar(talk_box, orient=tk.HORIZONTAL, length=200, mode='determinate')
        self.vol_bar.pack(fill=tk.X, padx=10, pady=(0, 4))

        # Nút Giữ để nói chuyện (Push to Talk - Giống App Tapo điện thoại)
        self.btn_hold_talk = tk.Button(talk_box, text="🎙️ GIỮ ĐỂ NÓI CHUYỆN (HOLD TO TALK)", font=("Segoe UI", 9, "bold"),
                                       bg="#059669", fg="white", activebackground="#047857", bd=0, pady=7, cursor="hand2")
        self.btn_hold_talk.pack(fill=tk.X, padx=10, pady=(2, 2))
        self.btn_hold_talk.bind("<ButtonPress-1>", self.on_hold_talk_press)
        self.btn_hold_talk.bind("<ButtonRelease-1>", self.on_hold_talk_release)

        # Nút Nói Trực Tiếp (Live Mic rảnh tay - Bật/Tắt)
        self.btn_live_talk = tk.Button(talk_box, text="🔊 BẬT/TẮT NÓI LIÊN TỤC (HANDS-FREE)", font=("Segoe UI", 8, "bold"),
                                       bg="#0284c7", fg="white", activebackground="#0369a1", bd=0, pady=4, cursor="hand2",
                                       command=self.toggle_live_talk)
        self.btn_live_talk.pack(fill=tk.X, padx=10, pady=(1, 2))
        self.btn_talkback = self.btn_live_talk  # Alias tương thích

        # Nút Thử Loa / Còi Tapo
        self.btn_test_speaker = tk.Button(talk_box, text="🔔 THỬ CÒI / LOA CAMERA TAPO", font=("Segoe UI", 8, "bold"),
                                          bg="#1e293b", fg="#fbbf24", activebackground="#334155", bd=0, pady=3, cursor="hand2",
                                          command=self.action_test_tapo_speaker)
        self.btn_test_speaker.pack(fill=tk.X, padx=10, pady=(1, 4))

        self.lbl_talk_status = tk.Label(talk_box, text="", font=("Segoe UI", 8), bg="#111c38", fg="#94a3b8", wraplength=240, cursor="hand2")
        self.lbl_talk_status.pack(pady=(0, 4))
        self.lbl_talk_status.bind("<Button-1>", lambda e: self.open_settings_dialog())

        # Các nút chức năng hệ thống
        btn_box = tk.Frame(right_panel, bg="#111c38")
        btn_box.pack(fill=tk.X, padx=10, pady=2)

        btn_emp = tk.Button(btn_box, text="👨‍💼 HỒ SƠ NHÂN SỰ & NGƯỜI LẠ", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="white",
                            activebackground="#334155", bd=0, pady=5, cursor="hand2", command=self.open_employee_manager_dialog)
        btn_emp.pack(fill=tk.X, pady=2)

        btn_sett = tk.Button(btn_box, text="⚙️ CÀI ĐẶT ĐA CAMERA & HỆ THỐNG", font=("Segoe UI", 9, "bold"), bg="#d97706", fg="white",
                             activebackground="#b45309", bd=0, pady=5, cursor="hand2", command=self.open_settings_dialog)
        btn_sett.pack(fill=tk.X, pady=2)

        btn_export = tk.Button(btn_box, text="📊 XUẤT BÁO CÁO EXCEL", font=("Segoe UI", 9, "bold"), bg="#059669", fg="white",
                               activebackground="#047857", bd=0, pady=5, cursor="hand2", command=self.action_export_excel)
        btn_export.pack(fill=tk.X, pady=2)

        # Danh sách vi phạm thời gian thực
        cards_frame = tk.LabelFrame(right_panel, text="⚠️ DANH SÁCH VI PHẠM & CẢNH BÁO", font=("Segoe UI", 9, "bold"),
                                    bg="#111c38", fg="#f87171", bd=1)
        cards_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        self.cards_container = tk.Frame(cards_frame, bg="#0b1329")
        self.cards_container.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Bàn điều khiển PTZ Tapo
        ptz_frame = tk.LabelFrame(right_panel, text="🎮 ĐIỀU KHIỂN XOAY TAPO PTZ", font=("Segoe UI", 8, "bold"),
                                  bg="#111c38", fg="#94a3b8", bd=1)
        ptz_frame.pack(fill=tk.X, padx=10, pady=4)

        grid_btn = tk.Frame(ptz_frame, bg="#111c38")
        grid_btn.pack(pady=3)

        btn_up = tk.Button(grid_btn, text="▲", font=("Segoe UI", 9, "bold"), width=5, bg="#0284c7", fg="white",
                           activebackground="#0369a1", bd=0, command=lambda: self.ptz_controller and self.ptz_controller.move(0.0, 0.3))
        btn_up.grid(row=0, column=1, padx=2, pady=1)

        btn_left = tk.Button(grid_btn, text="◄", font=("Segoe UI", 9, "bold"), width=5, bg="#0284c7", fg="white",
                             activebackground="#0369a1", bd=0, command=lambda: self.ptz_controller and self.ptz_controller.move(-0.3, 0.0))
        btn_left.grid(row=1, column=0, padx=2, pady=1)

        btn_stop = tk.Button(grid_btn, text="■", font=("Segoe UI", 9, "bold"), width=5, bg="#ef4444", fg="white",
                             activebackground="#dc2626", bd=0, command=lambda: self.ptz_controller and self.ptz_controller.move(0.0, 0.0, timeout=0.1))
        btn_stop.grid(row=1, column=1, padx=2, pady=1)

        btn_right = tk.Button(grid_btn, text="►", font=("Segoe UI", 9, "bold"), width=5, bg="#0284c7", fg="white",
                              activebackground="#0369a1", bd=0, command=lambda: self.ptz_controller and self.ptz_controller.move(0.3, 0.0))
        btn_right.grid(row=1, column=2, padx=2, pady=1)

        btn_down = tk.Button(grid_btn, text="▼", font=("Segoe UI", 9, "bold"), width=5, bg="#0284c7", fg="white",
                             activebackground="#0369a1", bd=0, command=lambda: self.ptz_controller and self.ptz_controller.move(0.0, -0.3))
        btn_down.grid(row=2, column=1, padx=2, pady=1)

        # Phím tắt bàn phím PTZ
        self.root.bind("<Up>", lambda event: self.ptz_controller and self.ptz_controller.move(0.0, 0.3))
        self.root.bind("<Down>", lambda event: self.ptz_controller and self.ptz_controller.move(0.0, -0.3))
        self.root.bind("<Left>", lambda event: self.ptz_controller and self.ptz_controller.move(-0.3, 0.0))
        self.root.bind("<Right>", lambda event: self.ptz_controller and self.ptz_controller.move(0.3, 0.0))

        btn_quit = tk.Button(right_panel, text="THOÁT HỆ THỐNG", font=("Segoe UI", 8, "bold"), bg="#334155", fg="#cbd5e1",
                             activebackground="#1e293b", bd=0, pady=4, cursor="hand2", command=self.on_closing)
        btn_quit.pack(side=tk.BOTTOM, pady=6, fill=tk.X, padx=10)

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def refresh_violation_cards(self):
        att_c, vio_c, stranger_c = self.db.get_today_stats()
        if hasattr(self, 'lbl_stat_att'):
            self.lbl_stat_att.config(text=str(att_c))
        if hasattr(self, 'lbl_stat_vio'):
            self.lbl_stat_vio.config(text=str(vio_c))
        if hasattr(self, 'lbl_stat_stranger'):
            self.lbl_stat_stranger.config(text=str(stranger_c))

        for widget in self.cards_container.winfo_children():
            widget.destroy()

        violations = self.db.fetch_recent_violations(limit=3)
        if not violations:
            tk.Label(self.cards_container, text="Chưa có vi phạm nào hôm nay.", font=("Segoe UI", 8, "italic"),
                     bg="#0b1329", fg="#64748b").pack(pady=20)

        for vio in violations:
            card = tk.Frame(self.cards_container, bg="#1e293b", bd=1, relief=tk.SOLID)
            card.pack(fill=tk.X, pady=3, padx=2)

            reg_img_path = vio[4] if vio[4] and os.path.exists(vio[4]) else None
            if not reg_img_path and vio[3] and os.path.exists(vio[3]):
                reg_img_path = vio[3]

            if reg_img_path:
                try:
                    img = Image.open(reg_img_path).resize((46, 46))
                    imgtk = ImageTk.PhotoImage(img)
                    lbl_img = tk.Label(card, image=imgtk, bg="#000000", bd=1, relief=tk.SOLID)
                    setattr(lbl_img, 'image', imgtk)
                    lbl_img.pack(side=tk.LEFT, padx=4, pady=4)
                except Exception:
                    pass

            info_frame = tk.Frame(card, bg="#1e293b")
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=2)

            is_unknown = (vio[0] == "Unknown")
            disp_name = "🚨 NGƯỜI LẠ" if is_unknown else f"👤 {vio[0]}"
            name_fg = "#fb923c" if is_unknown else "#f8fafc"

            lbl_name = tk.Label(info_frame, text=disp_name, font=("Segoe UI", 9, "bold"), bg="#1e293b", fg=name_fg)
            lbl_name.pack(anchor="w")

            lbl_type = tk.Label(info_frame, text=f"⚠️ {vio[2]}", font=("Segoe UI", 8, "bold"), bg="#1e293b", fg="#f87171")
            lbl_type.pack(anchor="w")

            time_part = vio[1].split(' ')[1] if ' ' in vio[1] else vio[1]
            lbl_time = tk.Label(info_frame, text=f"🕒 {time_part}", font=("Segoe UI", 8), bg="#1e293b", fg="#94a3b8")
            lbl_time.pack(anchor="w")

            card.bind("<Button-1>", lambda event, n=vio[0]: self.open_profile_for_user(n))
            info_frame.bind("<Button-1>", lambda event, n=vio[0]: self.open_profile_for_user(n))
            lbl_name.bind("<Button-1>", lambda event, n=vio[0]: self.open_profile_for_user(n))

        self.root.after(4000, self.refresh_violation_cards)

    def _play_alert_sound(self):
        """ Chỉ phát tiếng còi bíp nếu người dùng kích hoạt trong cài đặt """
        if not self.config_mgr.settings.get("beep_enabled", False):
            return
        try:
            import winsound
            winsound.Beep(1100, 220)
        except Exception:
            pass

    def open_profile_for_user(self, name):
        dlg = EmployeeManagerDialog(
            self.root, 
            self.db, 
            face_engine_callback=self.reload_face_database,
            get_frame_callback=self.get_latest_frame_for_capture
        )
        if name in ["Unknown", "Người lạ", "🚨 NGƯỜI LẠ"] or "Người lạ" in str(name) or "Stranger" in str(name):
            dlg.notebook.select(1)
        else:
            dlg.select_employee_by_name(name)

    def action_export_excel(self):
        success, path_or_err = self.db.export_to_excel()
        if success:
            try:
                os.startfile(path_or_err)
            except Exception:
                pass
            messagebox.showinfo("THÀNH CÔNG", f"Báo cáo Excel đã được xuất và mở tự động:\n{path_or_err}")
        else:
            messagebox.showerror("LỖI", f"Không thể xuất Excel:\n{path_or_err}")

    def toggle_stranger_voice_alert(self):
        """ Bật / Tắt cảnh báo an ninh giọng nói cho Người Lạ (mượt mà, không popup gây đơ) """
        v_cfg = self.config_mgr.settings.setdefault("voice", {})
        cur = v_cfg.get("stranger_enabled", v_cfg.get("enabled", True))
        new_state = not cur
        v_cfg["stranger_enabled"] = new_state
        v_cfg["enabled"] = new_state
        self.config_mgr.save_settings()

        # Nếu tắt giọng nói, ngắt ngay âm thanh đang phát
        if not new_state:
            try:
                self.voice_notifier.stop()
            except Exception:
                pass

        if new_state:
            self.btn_voice_toggle.config(text="🔊 BÁO NGƯỜI LẠ: BẬT", fg="#fbbf24")
            if hasattr(self, 'lbl_talk_status'):
                self.lbl_talk_status.config(text="🔊 Đã BẬT cảnh báo giọng nói an ninh người lạ!", fg="#fbbf24")
        else:
            self.btn_voice_toggle.config(text="🔇 BÁO NGƯỜI LẠ: TẮT", fg="#94a3b8")
            if hasattr(self, 'lbl_talk_status'):
                self.lbl_talk_status.config(text="🔇 Đã TẮT cảnh báo giọng nói an ninh người lạ!", fg="#94a3b8")

    def update_video_feed(self):
        """ Vòng lặp Render 30-50 FPS tối ưu cho toàn bộ Đa Camera """
        curr_time = time.time()
        self.frame_counter += 1

        try:
            if hasattr(self, 'lbl_clock'):
                self.lbl_clock.config(text=f"🕒 {datetime.now().strftime('%H:%M:%S')}")

            # Duyệt qua từng Camera trong hệ thống
            for cam_cfg in self.cameras:
                cid = cam_cfg.get("id")
                role = cam_cfg.get("role", "ppe")
                engine = self.cam_engines.get(cid)
                view = self.cam_views.get(cid)
                if not engine or not view:
                    continue

                ret, frame = engine.retrieve_frame()
                if ret and frame is not None:
                    view["lbl_badge"].config(text="ONLINE 🟢", fg="#34d399")
                    frame_h, frame_w = frame.shape[:2]

                    # -------------------------------------------------------------
                    # PHÂN HỆ A: CAMERA ĐIỂM DANH & QUÉT NGƯỜI LẠ
                    # -------------------------------------------------------------
                    if role == "attendance":
                        if self.frame_counter % 3 == 0:
                            with self.face_lock:
                                if self.latest_face_frames.get(cid) is None:
                                    self.latest_face_frames[cid] = frame.copy()

                        with self.face_lock:
                            current_face_results = list(self.cached_face_results.get(cid, []))

                        face_draw_results = []
                        strangers_in_frame = 0

                        for person_idx, face_res in enumerate(current_face_results):
                            f_bbox = face_res['bbox']
                            name = face_res['name']
                            sim = face_res['similarity']

                            fx1, fy1, fx2, fy2 = [int(v) for v in f_bbox]
                            face_center_x = (fx1 + fx2) / 2

                            if name == "Unknown":
                                strangers_in_frame += 1
                                entity_key = f"{cid}_Stranger_Grid_{int(face_center_x // 120)}"
                                status_str = "CHƯA ĐĂNG KÝ"

                                last_st_time = self.last_stranger_time.get(entity_key, 0)
                                if curr_time - last_st_time >= 15.0:
                                    self.last_stranger_time[entity_key] = curr_time
                                    crop_y1 = max(0, fy1 - 30)
                                    crop_y2 = min(frame_h, fy2 + 30)
                                    crop_x1 = max(0, fx1 - 30)
                                    crop_x2 = min(frame_w, fx2 + 30)
                                    stranger_crop = frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()
                                    if stranger_crop.size > 0:
                                        s_name = f"strangers/stranger_{int(curr_time)}_{person_idx}.jpg"
                                        cam_name = cam_cfg.get("name", "Cổng kiểm soát")
                                        def _dispatch_stranger_alert(scrop=stranger_crop, sname=s_name, cname=cam_name):
                                            try:
                                                cv2.imwrite(sname, scrop)
                                                self.db.save_stranger(sname, location=cname, ppe_status="Chưa đăng ký")
                                                self.zalo_notifier.send_violation_alert(
                                                    name="🚨 Người lạ chưa đăng ký",
                                                    violation_type="Người lạ xuất hiện tại khu vực kiểm soát",
                                                    evidence_path=sname,
                                                    location=cname
                                                )
                                                self.telegram_notifier.send_violation_alert(
                                                    name="🚨 Người lạ chưa đăng ký",
                                                    violation_type="Người lạ xuất hiện tại khu vực kiểm soát",
                                                    evidence_path=sname,
                                                    location=cname
                                                )
                                                self._play_alert_sound()
                                                self.voice_notifier.announce_stranger(location=cname)
                                            except Exception as ex:
                                                print(f"Lỗi gửi cảnh báo người lạ: {ex}")
                                        threading.Thread(target=_dispatch_stranger_alert, daemon=True).start()
                            else:
                                status_str = "ĐIỂM DANH THÀNH CÔNG"
                                self.active_workers[name] = curr_time
                                last_a_time = self.last_attendance_time.get(name, 0)
                                if curr_time - last_a_time >= self.cooldown_sec:
                                    self.last_attendance_time[name] = curr_time
                                    self.db.log_attendance(name=name, ppe_status="Cổng: Hợp lệ", confidence=sim, cooldown_seconds=self.cooldown_sec)

                            face_draw_results.append({
                                'bbox': f_bbox,
                                'name': name,
                                'similarity': sim,
                                'status_str': status_str
                            })

                        annotated_frame = render_camera_overlay(
                            frame, [], face_draw_results,
                            self.ppe_enabled, self.bgr_pass, self.bgr_viol
                        )

                        if strangers_in_frame > 0:
                            cv2.rectangle(annotated_frame, (10, 10), (490, 48), (15, 80, 220), -1)
                            cv2.putText(annotated_frame, f"CANH BAO: {strangers_in_frame} NGUOI LA CHUA DANG KY", (18, 35),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2)

                    # -------------------------------------------------------------
                    # PHÂN HỆ B: CAMERA HIỆN TRƯỜNG QUÉT BẢO HỘ PPE (HOÀN TOÀN BẤT ĐỒNG BỘ)
                    # -------------------------------------------------------------
                    else:
                        # Gửi khung hình cho luồng AI ngầm (3 frame một lần để không đầy RAM)
                        if self.frame_counter % 3 == 0:
                            with self.ppe_lock:
                                if self.latest_ppe_frames.get(cid) is None:
                                    self.latest_ppe_frames[cid] = frame.copy()

                        # Đọc kết quả suy luận mới nhất từ bộ nhớ đệm (0ms latency, không nghẽn GUI)
                        with self.ppe_lock:
                            cached_objects = list(self.cached_ppe_objects.get(cid, []))
                            cached_viols = list(self.cached_ppe_viols.get(cid, []))
                            last_scan = self.last_ppe_scan_timestamp.get(cid, 0.0)

                        target_badge = "ONLINE ⚡ AI ACTIVE" if curr_time - last_scan < 3.5 else "ONLINE 🟢"
                        target_fg = "#38bdf8" if curr_time - last_scan < 3.5 else "#34d399"
                        if view.get("last_badge_text") != target_badge:
                            view["last_badge_text"] = target_badge
                            view["lbl_badge"].config(text=target_badge, fg=target_fg)

                        annotated_frame = render_camera_overlay(
                            frame, cached_objects, [],
                            self.ppe_enabled, self.bgr_pass, self.bgr_viol
                        )

                        for v in cached_viols:
                            vx1, vy1, vx2, vy2 = [int(val) for val in v["box"]]
                            cv2.rectangle(annotated_frame, (vx1, vy1), (vx2, vy2), (0, 0, 255), 2)
                            cv2.rectangle(annotated_frame, (vx1, max(0, vy1 - 24)), (vx2, vy1), (0, 0, 255), -1)
                            disp_str = v.get("display", v["desc"])
                            cv2.putText(annotated_frame, disp_str[:35], (vx1 + 4, vy1 - 6),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

                        if len(cached_viols) > 0:
                            cv2.rectangle(annotated_frame, (10, 10), (490, 48), (20, 20, 190), -1)
                            cv2.putText(annotated_frame, f"CANH BAO: {len(cached_viols)} VI PHAM PPE TAI CONG TRUONG", (18, 35),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2)

                    # Đánh dấu trạng thái camera là online
                    view["last_state"] = "online"

                    # Nếu đang ở chế độ phóng to 1 camera khác, bỏ qua bước render giao diện để tối ưu tài nguyên và tránh xung đột kích thước
                    if self.zoomed_cam_id is not None and cid != self.zoomed_cam_id:
                        continue

                    # Scale Smart Fit thích ứng kích thước ô camera hiện tại (Giữ toàn cảnh chuẩn EHS, không cắt hình)
                    t_w = max(160, view["box"].winfo_width()) if view["box"].winfo_width() > 10 else 640
                    t_h = max(120, view["box"].winfo_height()) if view["box"].winfo_height() > 10 else 360

                    # Tối ưu siêu tốc: Thu nhỏ Smart Fit trên khung BGR trước, chỉ chuyển BGR->RGB trên canvas nhỏ
                    canvas_bgr = smart_fit_canvas(annotated_frame, target_w=t_w, target_h=t_h, fill_mode=False)
                    canvas_rgb = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(canvas_rgb)
                    imgtk = ImageTk.PhotoImage(image=img)
                    view["lbl_video"].imgtk = imgtk
                    view["lbl_video"].configure(image=imgtk, text="")

                else:
                    if view.get("last_state") != "offline":
                        view["last_state"] = "offline"
                        view["lbl_badge"].config(text="ĐANG KẾT NỐI... 🟡", fg="#fbbf24")
                        if self.zoomed_cam_id is not None and cid != self.zoomed_cam_id:
                            continue

                        t_w = max(160, view["box"].winfo_width()) if view["box"].winfo_width() > 10 else 640
                        t_h = max(120, view["box"].winfo_height()) if view["box"].winfo_height() > 10 else 360
                        offline_canvas = np.zeros((360, 640, 3), dtype=np.uint8)
                        cv2.putText(offline_canvas, f"[ {str(cid).upper()} - DANG KET NOI... ]", (150, 145),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (100, 180, 240), 2)
                        cv2.putText(offline_canvas, "Vui long kiem tra IP / nguon camera,", (155, 190),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (200, 200, 200), 1)
                        cv2.putText(offline_canvas, "hoac vao Cai Dat de doi Webcam / RTSP", (150, 220),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (200, 200, 200), 1)
                        canvas_bgr = smart_fit_canvas(offline_canvas, target_w=t_w, target_h=t_h, fill_mode=False)
                        canvas_rgb = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(canvas_rgb)
                        imgtk = ImageTk.PhotoImage(image=img)
                        view["lbl_video"].imgtk = imgtk
                        view["lbl_video"].configure(image=imgtk, text="")

            # Tính toán FPS mượt mà
            time_diff = curr_time - self.prev_time
            if time_diff > 0:
                self.fps = 1.0 / time_diff
            self.prev_time = curr_time

            if hasattr(self, 'lbl_fps_badge'):
                self.lbl_fps_badge.config(text=f"⚡ {self.fps:.0f} FPS")

        except Exception as e:
            print(f"Lỗi trong vòng lặp render: {e}")

        # Tối ưu nhịp render: 30-50 FPS
        elapsed_ms = (time.time() - curr_time) * 1000
        next_delay = max(1, int(30 - elapsed_ms))
        self.root.after(next_delay, self.update_video_feed)

    def on_closing(self):
        self.is_running = False
        if self.talkback:
            self.talkback.close()
        for eng in self.cam_engines.values():
            try:
                eng.stop()
            except Exception:
                pass
        if self.ptz_controller:
            self.ptz_controller.close()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = SmartEHSManagementApp(root)
    root.mainloop()