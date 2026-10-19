import os
import shutil
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import cv2
import numpy as np


class CameraCaptureWindow(tk.Toplevel):
    """
    Cửa sổ Chụp Ảnh Khuôn Mặt Trực Tiếp từ Camera (Live Video Preview & Snapshot)
    - Truy xuất khung hình trực tiếp từ luồng camera đang chạy của hệ thống (0ms trễ, không xung đột phần cứng)
    - Hỗ trợ căn chỉnh khuôn mặt chuẩn với khung ngắm điện tử (Reticle Guide)
    - Chụp ảnh, kiểm tra ảnh chụp trước khi chính thức lưu hồ sơ nhân sự
    """
    def __init__(self, parent, get_frame_callback=None, on_captured_callback=None):
        super().__init__(parent)
        self.title("📸 CHỤP ẢNH ĐĂNG KÝ KHUÔN MẶT")
        self.geometry("620x540")
        self.minsize(540, 460)
        self.configure(bg="#0b1329")
        self.transient(parent)
        self.grab_set()

        self.get_frame_callback = get_frame_callback
        self.on_captured_callback = on_captured_callback
        self.captured_clean_frame = None
        self.is_running = True
        self.local_cap = None
        self.after_id = None

        # Dự phòng webcam cục bộ
        if not self.get_frame_callback:
            self._try_open_local_cam()

        self._build_ui()
        self._update_loop()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _try_open_local_cam(self):
        if self.local_cap and self.local_cap.isOpened():
            return
        try:
            for idx in [0, 1]:
                c = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                if c and c.isOpened():
                    ret, f = c.read()
                    if ret and f is not None:
                        self.local_cap = c
                        return
                    c.release()
        except Exception:
            self.local_cap = None

    def _build_ui(self):
        # Header
        h_frame = tk.Frame(self, bg="#1e293b", height=42)
        h_frame.pack(fill=tk.X)
        h_frame.pack_propagate(False)

        tk.Label(h_frame, text="📷 ĐĂNG KÝ HỒ SƠ: CHỤP ẢNH TỪ CAMERA TRỰC TIẾP",
                 font=("Segoe UI", 10, "bold"), bg="#1e293b", fg="#38bdf8").pack(side=tk.LEFT, padx=12, pady=10)

        self.lbl_status = tk.Label(h_frame, text="LIVE FEED 🟢",
                                   font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#34d399")
        self.lbl_status.pack(side=tk.RIGHT, padx=12)

        # Video canvas / label
        self.video_box = tk.Frame(self, bg="#050a17", bd=2, relief=tk.SOLID)
        self.video_box.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        self.lbl_video = tk.Label(self.video_box, bg="#050a17")
        self.lbl_video.pack(fill=tk.BOTH, expand=True)

        # Bottom control bar
        self.ctrl_bar = tk.Frame(self, bg="#0b1329", height=54)
        self.ctrl_bar.pack(fill=tk.X, padx=12, pady=(0, 10))

        self.btn_capture = tk.Button(self.ctrl_bar, text="📸 BẤM CHỤP ẢNH", font=("Segoe UI", 10, "bold"),
                                     bg="#0284c7", fg="white", activebackground="#0369a1", bd=0, padx=20, pady=8,
                                     cursor="hand2", command=self._action_snap)
        self.btn_capture.pack(side=tk.LEFT, padx=5)

        self.btn_retake = tk.Button(self.ctrl_bar, text="🔄 CHỤP LẠI", font=("Segoe UI", 9, "bold"),
                                    bg="#475569", fg="white", activebackground="#334155", bd=0, padx=14, pady=8,
                                    cursor="hand2", command=self._action_retake)

        self.btn_confirm = tk.Button(self.ctrl_bar, text="✅ SỬ DỤNG ẢNH NÀY", font=("Segoe UI", 10, "bold"),
                                     bg="#059669", fg="white", activebackground="#047857", bd=0, padx=16, pady=8,
                                     cursor="hand2", command=self._action_confirm)

        self.btn_cancel = tk.Button(self.ctrl_bar, text="ĐÓNG", font=("Segoe UI", 9),
                                    bg="#334155", fg="#cbd5e1", activebackground="#1e293b", bd=0, padx=14, pady=8,
                                    cursor="hand2", command=self._on_close)
        self.btn_cancel.pack(side=tk.RIGHT, padx=5)

    def _update_loop(self):
        if not self.is_running:
            return

        if self.captured_clean_frame is None:
            # Đang ở chế độ xem trực tiếp (LIVE)
            ret = False
            raw_frame = None

            if self.get_frame_callback:
                try:
                    ret, raw_frame = self.get_frame_callback()
                except Exception:
                    ret, raw_frame = False, None

            if not ret or raw_frame is None:
                if self.local_cap is None or not self.local_cap.isOpened():
                    self._try_open_local_cam()
                if self.local_cap and self.local_cap.isOpened():
                    try:
                        ret, raw_frame = self.local_cap.read()
                    except Exception:
                        ret, raw_frame = False, None

            if ret and raw_frame is not None:
                self.current_live_frame = raw_frame.copy()
                disp_frame = raw_frame.copy()
                fh, fw = disp_frame.shape[:2]

                # Vẽ khung hướng dẫn căn chỉnh khuôn mặt (Face Reticle Guide)
                cx, cy = fw // 2, int(fh * 0.48)
                rx, ry = int(fw * 0.22), int(fh * 0.32)
                cv2.ellipse(disp_frame, (cx, cy), (rx, ry), 0, 0, 360, (56, 189, 248), 2)
                cv2.putText(disp_frame, "CAN CHINH KHUON MAT VAO GIUA KHUNG", (cx - 160, cy + ry + 28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1, cv2.LINE_AA)

                self._render_to_label(disp_frame)
            else:
                blank = np.zeros((360, 540, 3), dtype=np.uint8)
                cv2.putText(blank, "DANG KET NOI CAMERA...", (140, 180),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (100, 150, 255), 2)
                self._render_to_label(blank)

        self.after_id = self.after(33, self._update_loop)

    def _render_to_label(self, bgr_img):
        try:
            vw = max(320, self.video_box.winfo_width()) if self.video_box.winfo_width() > 10 else 540
            vh = max(240, self.video_box.winfo_height()) if self.video_box.winfo_height() > 10 else 360
            h, w = bgr_img.shape[:2]
            scale = min(vw / w, vh / h)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            resized = cv2.resize(bgr_img, (nw, nh), interpolation=cv2.INTER_AREA)

            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            im = Image.fromarray(rgb)
            imgtk = ImageTk.PhotoImage(image=im)
            self._current_imgtk = imgtk
            self.lbl_video.configure(image=imgtk)
        except Exception:
            pass

    def _action_snap(self):
        if hasattr(self, 'current_live_frame') and self.current_live_frame is not None:
            self.captured_clean_frame = self.current_live_frame.copy()
            self.lbl_status.config(text="ĐÃ CHỤP ẢNH ⏸️", fg="#fbbf24")
            self.btn_capture.pack_forget()
            self.btn_retake.pack(side=tk.LEFT, padx=5)
            self.btn_confirm.pack(side=tk.LEFT, padx=5)

            preview = self.captured_clean_frame.copy()
            cv2.rectangle(preview, (4, 4), (preview.shape[1]-4, preview.shape[0]-4), (52, 211, 153), 4)
            self._render_to_label(preview)

    def _action_retake(self):
        self.captured_clean_frame = None
        self.lbl_status.config(text="LIVE FEED 🟢", fg="#34d399")
        self.btn_retake.pack_forget()
        self.btn_confirm.pack_forget()
        self.btn_capture.pack(side=tk.LEFT, padx=5)

    def _action_confirm(self):
        if self.captured_clean_frame is not None:
            os.makedirs("faces", exist_ok=True)
            saved_path = f"faces/_tmp_capture_{int(time.time())}.jpg"
            cv2.imwrite(saved_path, self.captured_clean_frame)
            if self.on_captured_callback:
                self.on_captured_callback(saved_path)
            self._on_close()

    def _on_close(self):
        self.is_running = False
        if self.after_id:
            try:
                self.after_cancel(self.after_id)
            except Exception:
                pass
        if self.local_cap:
            try:
                self.local_cap.release()
            except Exception:
                pass
            self.local_cap = None
        self.destroy()


class EmployeeManagerDialog(tk.Toplevel):
    """
    Cửa sổ quản lý toàn diện:
    1. Hồ sơ nhân viên: Thêm mới, Sửa thông tin, Xóa nhân sự, Nhập hàng loạt, Chụp ảnh trực tiếp từ camera.
    2. Hồ sơ người lạ: Quản lý chi tiết nhật ký xâm nhập, xem ảnh bằng chứng, đăng ký thành nhân viên.
    """
    def __init__(self, parent, db, face_engine_callback=None, get_frame_callback=None):
        super().__init__(parent)
        self.title("🛡️ QUẢN LÝ HỒ SƠ NHÂN SỰ & NHẬT KÝ NGƯỜI LẠ")
        self.geometry("980x680")
        self.minsize(880, 600)
        self.configure(bg="#0b1329")
        
        self.db = db
        self.face_engine_callback = face_engine_callback
        self.get_frame_callback = get_frame_callback
        self.all_employees = []
        self.stranger_data_map = {}
        self.vio_data_map = {}
        self.avatar_imgtk = None
        self.evidence_imgtk = None
        self.stranger_imgtk = None

        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self.refresh_employee_list()
        self.refresh_strangers_list()

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure("TNotebook", background="#0b1329", borderwidth=0)
        style.configure("TNotebook.Tab", background="#1e293b", foreground="#94a3b8",
                        font=("Segoe UI", 9, "bold"), padding=[14, 6])
        style.map("TNotebook.Tab",
                  background=[("selected", "#0284c7")],
                  foreground=[("selected", "#ffffff")])

        style.configure("Treeview", background="#0f172a", foreground="#e2e8f0",
                        fieldbackground="#0f172a", font=("Segoe UI", 9), rowheight=24)
        style.configure("Treeview.Heading", background="#1e293b", foreground="#38bdf8",
                        font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", "#0369a1")])

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        # =========================================================
        # TAB 1: QUẢN LÝ HỒ SƠ NHÂN VIÊN
        # =========================================================
        tab_emp = tk.Frame(self.notebook, bg="#111c38")
        self.notebook.add(tab_emp, text=" 👥 Hồ Sơ Nhân Viên ")

        # --- CỘT TRÁI: DANH SÁCH & CÁC NÚT THAO TÁC ---
        left_frame = tk.Frame(tab_emp, bg="#111c38", width=300)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=12, pady=10)
        left_frame.pack_propagate(False)

        # Ô tìm kiếm nhân viên
        search_box = tk.Frame(left_frame, bg="#1e293b", bd=1, relief=tk.SOLID)
        search_box.pack(fill=tk.X, pady=(0, 8))
        tk.Label(search_box, text="🔍", font=("Segoe UI", 9), bg="#1e293b", fg="#94a3b8").pack(side=tk.LEFT, padx=5)
        self.entry_search = tk.Entry(search_box, font=("Segoe UI", 9), bg="#1e293b", fg="white",
                                     insertbackground="white", bd=0)
        self.entry_search.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=5)
        self.entry_search.bind("<KeyRelease>", self.on_search_employees)

        tk.Label(left_frame, text="DANH SÁCH NHÂN SỰ:", font=("Segoe UI", 9, "bold"),
                 bg="#111c38", fg="#38bdf8").pack(anchor="w", pady=(0, 4))
        
        # Listbox nhân viên
        self.emp_listbox = tk.Listbox(left_frame, font=("Segoe UI", 9), bg="#0f172a", fg="#f8fafc",
                                      selectbackground="#0284c7", selectforeground="white",
                                      bd=1, relief=tk.SOLID, highlightthickness=0)
        self.emp_listbox.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.emp_listbox.bind("<<ListboxSelect>>", self.on_employee_select)

        # 4 Nút hành động nhân sự
        btn_box = tk.Frame(left_frame, bg="#111c38")
        btn_box.pack(fill=tk.X)

        btn_add = tk.Button(btn_box, text="➕ THÊM NHÂN VIÊN", font=("Segoe UI", 9, "bold"),
                            bg="#059669", fg="white", activebackground="#047857", bd=0, pady=5,
                            cursor="hand2", command=self.open_add_employee_dialog)
        btn_add.pack(fill=tk.X, pady=2)

        btn_edit = tk.Button(btn_box, text="✏️ SỬA THÔNG TIN", font=("Segoe UI", 9, "bold"),
                             bg="#2563eb", fg="white", activebackground="#1d4ed8", bd=0, pady=5,
                             cursor="hand2", command=self.open_edit_employee_dialog)
        btn_edit.pack(fill=tk.X, pady=2)

        btn_del = tk.Button(btn_box, text="🗑️ XÓA NHÂN VIÊN", font=("Segoe UI", 9, "bold"),
                            bg="#dc2626", fg="white", activebackground="#b91c1c", bd=0, pady=5,
                            cursor="hand2", command=self.action_delete_employee)
        btn_del.pack(fill=tk.X, pady=2)

        btn_multi = tk.Button(btn_box, text="📁 TẢI HÀNG LOẠT (3-4 NGƯỜI)", font=("Segoe UI", 8, "bold"),
                              bg="#475569", fg="#e2e8f0", activebackground="#334155", bd=0, pady=4,
                              cursor="hand2", command=self.action_add_multiple_employees)
        btn_multi.pack(fill=tk.X, pady=2)

        # --- CỘT PHẢI: CHI TIẾT HỒ SƠ & LỊCH SỬ ---
        right_frame = tk.Frame(tab_emp, bg="#0b1329", bd=1, relief=tk.SOLID)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(0, 12), pady=10)

        # Khung Thông tin tóm tắt & Avatar
        top_info = tk.Frame(right_frame, bg="#1e293b", bd=1, relief=tk.SOLID)
        top_info.pack(fill=tk.X, padx=10, pady=10)

        # Khung Avatar riêng biệt cố định kích thước 120x120
        avatar_box = tk.Frame(top_info, bg="#0f172a", width=120, height=120, bd=1, relief=tk.SOLID)
        avatar_box.pack(side=tk.LEFT, padx=10, pady=10)
        avatar_box.pack_propagate(False)

        self.lbl_avatar = tk.Label(avatar_box, text="[Ảnh Chân Dung]", bg="#0f172a", fg="#64748b", font=("Segoe UI", 9))
        self.lbl_avatar.pack(fill=tk.BOTH, expand=True)

        meta_frame = tk.Frame(top_info, bg="#1e293b")
        meta_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.lbl_emp_name = tk.Label(meta_frame, text="Họ & Tên: ---", font=("Segoe UI", 13, "bold"),
                                     bg="#1e293b", fg="#38bdf8")
        self.lbl_emp_name.pack(anchor="w", pady=2)

        self.lbl_emp_role = tk.Label(meta_frame, text="Chức vụ: ---", font=("Segoe UI", 10),
                                     bg="#1e293b", fg="#cbd5e1")
        self.lbl_emp_role.pack(anchor="w", pady=2)

        self.lbl_emp_stats = tk.Label(meta_frame, text="Tổng lượt điểm danh: 0  |  Vi phạm: 0",
                                      font=("Segoe UI", 9, "italic"), bg="#1e293b", fg="#94a3b8")
        self.lbl_emp_stats.pack(anchor="w", pady=4)

        # Tabs Lịch sử Chấm công & Lịch sử Vi phạm
        hist_notebook = ttk.Notebook(right_frame)
        hist_notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Sub-tab: Lịch sử Chấm công
        tab_att = tk.Frame(hist_notebook, bg="#111c38")
        hist_notebook.add(tab_att, text=" ⏱️ Lịch Sử Chấm Công ")

        self.tree_att = ttk.Treeview(tab_att, columns=("time", "status"), show="headings", height=8)
        self.tree_att.heading("time", text="Thời Gian Ghi Nhận")
        self.tree_att.heading("status", text="Trạng Thái PPE")
        self.tree_att.column("time", width=180, anchor="center")
        self.tree_att.column("status", width=260, anchor="center")
        self.tree_att.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Sub-tab: Lịch sử Vi phạm (có ảnh bằng chứng)
        tab_vio = tk.Frame(hist_notebook, bg="#111c38")
        hist_notebook.add(tab_vio, text=" ⚠️ Lịch Sử Vi Phạm (Có Ảnh) ")

        # Panel bên phải: Xem ảnh bằng chứng vi phạm đầy đủ (pack bên phải trước để giữ nguyên chiều rộng)
        evidence_panel = tk.Frame(tab_vio, bg="#0b1329", width=290, bd=1, relief=tk.SOLID)
        evidence_panel.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(4, 6), pady=6)
        evidence_panel.pack_propagate(False)

        header_ev = tk.Frame(evidence_panel, bg="#0b1329")
        header_ev.pack(fill=tk.X, padx=8, pady=(6, 4))
        tk.Label(header_ev, text="📸 ẢNH BẰNG CHỨNG VI PHẠM", font=("Segoe UI", 9, "bold"),
                 bg="#0b1329", fg="#38bdf8").pack(side=tk.LEFT)

        self.img_container = tk.Frame(evidence_panel, bg="#050a17", bd=1, relief=tk.SOLID)
        self.img_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))
        self.img_container.pack_propagate(False)

        self.lbl_evidence_img = tk.Label(self.img_container, text="[Chọn dòng để xem ảnh]",
                                         bg="#050a17", fg="#64748b", font=("Segoe UI", 9))
        self.lbl_evidence_img.pack(fill=tk.BOTH, expand=True)
        self.lbl_evidence_img.bind("<Double-Button-1>", self.open_full_evidence)

        self.btn_view_full_ev = tk.Button(evidence_panel, text="🔍 Mở ảnh gốc toàn màn hình",
                                          font=("Segoe UI", 8), bg="#1e293b", fg="#38bdf8",
                                          activebackground="#0284c7", activeforeground="white",
                                          bd=0, pady=4, state=tk.DISABLED, cursor="hand2",
                                          command=self.open_full_evidence)
        self.btn_view_full_ev.pack(fill=tk.X, padx=8, pady=(0, 6))

        # Bảng Treeview vi phạm (bên trái, chiếm toàn bộ phần còn lại)
        self.tree_vio = ttk.Treeview(tab_vio, columns=("time", "type"), show="headings", height=6)
        self.tree_vio.heading("time", text="Thời Gian")
        self.tree_vio.heading("type", text="Hành Vi Vi Phạm")
        self.tree_vio.column("time", width=140, anchor="center")
        self.tree_vio.column("type", width=220, anchor="w")
        self.tree_vio.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 2), pady=6)
        self.tree_vio.bind("<<TreeviewSelect>>", self.on_violation_select)

        # =========================================================
        # TAB 2: HỒ SƠ & NHẬT KÝ NGƯỜI LẠ (STRANGER RECORDS)
        # =========================================================
        tab_stranger = tk.Frame(self.notebook, bg="#111c38")
        self.notebook.add(tab_stranger, text=" 🚨 Hồ Sơ & Nhật Ký Người Lạ ")

        # Left: Bảng nhật ký người lạ
        st_left = tk.Frame(tab_stranger, bg="#111c38")
        st_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=10)

        header_st = tk.Frame(st_left, bg="#111c38")
        header_st.pack(fill=tk.X, pady=(0, 6))
        tk.Label(header_st, text="NHẬT KÝ XÂM NHẬP / NGƯỜI LẠ PHÁT HIỆN:", font=("Segoe UI", 10, "bold"),
                 bg="#111c38", fg="#f97316").pack(side=tk.LEFT)

        btn_refresh_st = tk.Button(header_st, text="🔄 Làm Mới", font=("Segoe UI", 8), bg="#334155", fg="white",
                                   bd=0, padx=6, pady=2, cursor="hand2", command=self.refresh_strangers_list)
        btn_refresh_st.pack(side=tk.RIGHT)

        self.tree_strangers = ttk.Treeview(st_left, columns=("id", "time", "location", "ppe"), show="headings")
        self.tree_strangers.heading("id", text="ID")
        self.tree_strangers.heading("time", text="Thời Gian")
        self.tree_strangers.heading("location", text="Vị Trí Ghi Nhận")
        self.tree_strangers.heading("ppe", text="Tình Trạng An Toàn (PPE)")

        self.tree_strangers.column("id", width=40, anchor="center")
        self.tree_strangers.column("time", width=140, anchor="center")
        self.tree_strangers.column("location", width=120, anchor="center")
        self.tree_strangers.column("ppe", width=190, anchor="w")
        self.tree_strangers.pack(fill=tk.BOTH, expand=True)
        self.tree_strangers.bind("<<TreeviewSelect>>", self.on_stranger_select)

        # Nút dọn dẹp ảnh người lạ
        btn_clean_st = tk.Button(st_left, text="🧹 XÓA TẤT CẢ ẢNH NGƯỜI LẠ", font=("Segoe UI", 8, "bold"),
                                 bg="#7f1d1d", fg="#fca5a5", activebackground="#991b1b", bd=0, pady=4,
                                 cursor="hand2", command=self.action_clear_all_strangers)
        btn_clean_st.pack(fill=tk.X, pady=(6, 0))

        # Right: Chi tiết hồ sơ người lạ được chọn
        st_right = tk.Frame(tab_stranger, bg="#0b1329", width=340, bd=1, relief=tk.SOLID)
        st_right.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12), pady=10)
        st_right.pack_propagate(False)

        tk.Label(st_right, text="HỒ SƠ ĐỐI TƯỢNG", font=("Segoe UI", 10, "bold"),
                 bg="#0b1329", fg="#38bdf8").pack(pady=(12, 6))

        st_img_box = tk.Frame(st_right, bg="#050a17", width=280, height=210, bd=1, relief=tk.SOLID)
        st_img_box.pack(padx=12, pady=6)
        st_img_box.pack_propagate(False)

        self.lbl_st_img = tk.Label(st_img_box, text="[Chọn một đối tượng]", bg="#050a17", fg="#64748b", font=("Segoe UI", 9))
        self.lbl_st_img.pack(fill=tk.BOTH, expand=True)
        self.lbl_st_img.bind("<Double-Button-1>", self.open_full_stranger_img)

        self.lbl_st_time = tk.Label(st_right, text="Thời gian: ---", font=("Segoe UI", 9),
                                    bg="#0b1329", fg="#cbd5e1")
        self.lbl_st_time.pack(anchor="w", padx=16, pady=2)

        self.lbl_st_loc = tk.Label(st_right, text="Vị trí: ---", font=("Segoe UI", 9),
                                   bg="#0b1329", fg="#cbd5e1")
        self.lbl_st_loc.pack(anchor="w", padx=16, pady=2)

        self.lbl_st_ppe = tk.Label(st_right, text="Trạng thái: ---", font=("Segoe UI", 9),
                                   bg="#0b1329", fg="#f87171")
        self.lbl_st_ppe.pack(anchor="w", padx=16, pady=2)

        # Cụm 2 nút xử lý người lạ
        st_btn_box = tk.Frame(st_right, bg="#0b1329")
        st_btn_box.pack(fill=tk.X, padx=16, pady=(16, 0))

        self.btn_convert_st = tk.Button(st_btn_box, text="👤 ĐĂNG KÝ THÀNH NHÂN VIÊN", font=("Segoe UI", 9, "bold"),
                                        bg="#d97706", fg="white", activebackground="#b45309", bd=0, pady=7,
                                        cursor="hand2", state=tk.DISABLED, command=self.action_convert_current_stranger)
        self.btn_convert_st.pack(fill=tk.X, pady=3)

        self.btn_del_st = tk.Button(st_btn_box, text="🗑️ XÓA HỒ SƠ NÀY", font=("Segoe UI", 9, "bold"),
                                    bg="#dc2626", fg="white", activebackground="#b91c1c", bd=0, pady=6,
                                    cursor="hand2", state=tk.DISABLED, command=self.action_delete_current_stranger)
        self.btn_del_st.pack(fill=tk.X, pady=3)

    # =========================================================
    # LOGIC TAB 1: NHÂN SỰ (THÊM, SỬA, XÓA, TÌM KIẾM)
    # =========================================================
    def refresh_employee_list(self):
        self.all_employees = self.db.fetch_all_employees()
        self.on_search_employees(None)

    def on_search_employees(self, event):
        keyword = self.entry_search.get().strip().lower()
        self.emp_listbox.delete(0, tk.END)
        for emp in self.all_employees:
            name, role, _ = emp
            if not keyword or keyword in name.lower() or keyword in role.lower():
                self.emp_listbox.insert(tk.END, name)

        if self.emp_listbox.size() > 0:
            self.emp_listbox.selection_set(0)
            self.emp_listbox.event_generate("<<ListboxSelect>>")
        else:
            self.lbl_emp_name.config(text="Họ & Tên: (Không tìm thấy)")
            self.lbl_emp_role.config(text="Chức vụ: ---")
            self.lbl_emp_stats.config(text="Tổng lượt điểm danh: 0  |  Vi phạm: 0")
            self.lbl_avatar.config(image="", text="[Chưa có ảnh]")

    def select_employee_by_name(self, target_name):
        for idx in range(self.emp_listbox.size()):
            if self.emp_listbox.get(idx) == target_name:
                self.emp_listbox.selection_clear(0, tk.END)
                self.emp_listbox.selection_set(idx)
                self.emp_listbox.event_generate("<<ListboxSelect>>")
                break

    def on_employee_select(self, event):
        widget = event.widget
        selection = widget.curselection()
        if selection:
            name = widget.get(selection[0])
            emp, att_logs, vio_logs = self.db.fetch_employee_profile(name)
            
            if emp:
                self.lbl_emp_name.config(text=f"Họ & Tên: {emp[0]}")
                self.lbl_emp_role.config(text=f"Chức vụ: {emp[1]}")
                self.lbl_emp_stats.config(text=f"Tổng lượt điểm danh: {len(att_logs)}  |  Vi phạm: {len(vio_logs)}")

                # Nạp ảnh Avatar
                if emp[2] and os.path.exists(emp[2]):
                    try:
                        pil_img = Image.open(emp[2])
                        w, h = pil_img.size
                        scale = min(120 / w, 120 / h)
                        nw = max(1, int(w * scale))
                        nh = max(1, int(h * scale))
                        resized_img = pil_img.resize((nw, nh), Image.Resampling.LANCZOS)
                        imgtk = ImageTk.PhotoImage(resized_img)
                        self.lbl_avatar.config(image=imgtk, text="")
                        self.avatar_imgtk = imgtk
                        setattr(self.lbl_avatar, 'image', imgtk)
                    except Exception:
                        self.lbl_avatar.config(image="", text="[Lỗi đọc ảnh]")
                else:
                    self.lbl_avatar.config(image="", text="[Chưa có ảnh]")

                # Nạp Bảng Chấm công
                for item in self.tree_att.get_children():
                    self.tree_att.delete(item)
                for log in att_logs:
                    self.tree_att.insert("", tk.END, values=(log[0], log[1]))

                # Nạp Bảng Vi phạm
                for item in self.tree_vio.get_children():
                    self.tree_vio.delete(item)
                self.vio_data_map = {}
                for log in vio_logs:
                    item_id = self.tree_vio.insert("", tk.END, values=(log[0], log[1]))
                    self.vio_data_map[item_id] = log[2]

                self.lbl_evidence_img.config(image="", text="[Chọn dòng để xem ảnh]")
                if hasattr(self, 'btn_view_full_ev'):
                    self.btn_view_full_ev.config(state=tk.DISABLED)

    def on_violation_select(self, event):
        selected = self.tree_vio.selection()
        if selected:
            evidence_path = self.vio_data_map.get(selected[0])
            self.current_evidence_path = evidence_path
            if evidence_path and os.path.exists(evidence_path):
                try:
                    pil_img = Image.open(evidence_path)
                    w, h = pil_img.size
                    max_w = max(180, self.img_container.winfo_width()) if self.img_container.winfo_width() > 10 else 270
                    max_h = max(140, self.img_container.winfo_height()) if self.img_container.winfo_height() > 10 else 210
                    scale = min(max_w / w, max_h / h)
                    nw = max(1, int(w * scale))
                    nh = max(1, int(h * scale))
                    resized_img = pil_img.resize((nw, nh), Image.Resampling.LANCZOS)
                    imgtk = ImageTk.PhotoImage(resized_img)
                    self.lbl_evidence_img.config(image=imgtk, text="")
                    self.evidence_imgtk = imgtk
                    setattr(self.lbl_evidence_img, 'image', imgtk)
                    if hasattr(self, 'btn_view_full_ev'):
                        self.btn_view_full_ev.config(state=tk.NORMAL)
                except Exception:
                    self.lbl_evidence_img.config(image="", text="[Lỗi nạp ảnh]")
                    if hasattr(self, 'btn_view_full_ev'):
                        self.btn_view_full_ev.config(state=tk.DISABLED)
            else:
                self.lbl_evidence_img.config(image="", text="[Không có file ảnh]")
                if hasattr(self, 'btn_view_full_ev'):
                    self.btn_view_full_ev.config(state=tk.DISABLED)

    def open_full_evidence(self, event=None):
        """ Mở ảnh vi phạm độ phân giải gốc bằng trình xem ảnh mặc định của Windows """
        if hasattr(self, 'current_evidence_path') and self.current_evidence_path and os.path.exists(self.current_evidence_path):
            try:
                os.startfile(self.current_evidence_path)
            except Exception as e:
                print(f"Lỗi mở ảnh gốc: {e}")

    def open_add_employee_dialog(self):
        """ Mở Form Thêm Mới Nhân Viên """
        dlg = tk.Toplevel(self)
        dlg.title("➕ THÊM NHÂN VIÊN MỚI")
        dlg.geometry("450x380")
        dlg.configure(bg="#0b1329")
        dlg.transient(self)
        dlg.grab_set()

        selected_image_path: list[str | None] = [None]

        tk.Label(dlg, text="HỌ VÀ TÊN NHÂN VIÊN (*):", font=("Segoe UI", 9, "bold"),
                 bg="#0b1329", fg="#38bdf8").pack(anchor="w", padx=20, pady=(15, 2))
        entry_name = tk.Entry(dlg, font=("Segoe UI", 10), bg="#1e293b", fg="white", insertbackground="white")
        entry_name.pack(fill=tk.X, padx=20, pady=(0, 10))

        tk.Label(dlg, text="CHỨC VỤ / VỊ TRÍ CÔNG TÁC:", font=("Segoe UI", 9, "bold"),
                 bg="#0b1329", fg="#38bdf8").pack(anchor="w", padx=20, pady=(0, 2))
        cb_role = ttk.Combobox(dlg, font=("Segoe UI", 10),
                               values=["Công nhân", "Kỹ sư công trường", "Giám sát an toàn EHS",
                                       "Chỉ huy trưởng", "Đội trưởng thi công", "Thầu phụ", "Bảo vệ"])
        cb_role.set("Công nhân")
        cb_role.pack(fill=tk.X, padx=20, pady=(0, 12))

        # Chọn ảnh hoặc chụp webcam
        frame_img_select = tk.Frame(dlg, bg="#1e293b", bd=1, relief=tk.SOLID)
        frame_img_select.pack(fill=tk.X, padx=20, pady=(0, 15), ipady=6)

        lbl_img_preview = tk.Label(frame_img_select, text="Chưa chọn ảnh chân dung", font=("Segoe UI", 8),
                                   bg="#1e293b", fg="#94a3b8")
        lbl_img_preview.pack(pady=4)

        btn_row = tk.Frame(frame_img_select, bg="#1e293b")
        btn_row.pack()

        def choose_file():
            fp = filedialog.askopenfilename(title="Chọn ảnh khuôn mặt nhân viên",
                                            filetypes=[("Image Files", "*.jpg *.jpeg *.png")])
            if fp:
                selected_image_path[0] = fp
                lbl_img_preview.config(text=f"✓ Đã chọn: {os.path.basename(fp)}", fg="#34d399")

        def capture_webcam():
            def on_captured(saved_path):
                selected_image_path[0] = saved_path
                lbl_img_preview.config(text=f"✓ Đã chụp ảnh thành công từ Camera: {os.path.basename(saved_path)}", fg="#34d399")

            CameraCaptureWindow(dlg, get_frame_callback=self.get_frame_callback, on_captured_callback=on_captured)

        tk.Button(btn_row, text="📁 Chọn từ máy tính", font=("Segoe UI", 8, "bold"),
                  bg="#334155", fg="white", bd=0, padx=8, pady=3, cursor="hand2", command=choose_file).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_row, text="📷 Chụp từ Camera", font=("Segoe UI", 8, "bold"),
                  bg="#0284c7", fg="white", bd=0, padx=8, pady=3, cursor="hand2", command=capture_webcam).pack(side=tk.LEFT, padx=4)

        def save_new_employee():
            name = entry_name.get().strip()
            role = cb_role.get().strip() or "Công nhân"
            if not name:
                messagebox.showwarning("CẢNH BÁO", "Vui lòng nhập Họ và Tên nhân viên!", parent=dlg)
                return

            if not selected_image_path[0] or not os.path.exists(selected_image_path[0]):
                messagebox.showwarning("CẢNH BÁO", "Vui lòng chọn hoặc chụp ảnh chân dung cho nhân viên!", parent=dlg)
                return

            dest_face = os.path.join("faces", f"{name}.jpg").replace("\\", "/")
            try:
                shutil.copy(selected_image_path[0], dest_face)
            except Exception as e:
                pass

            success = self.db.add_employee(name, role, dest_face)
            if success:
                messagebox.showinfo("THÀNH CÔNG", f"Đã thêm mới nhân sự: {name} ({role})", parent=dlg)
                dlg.destroy()
                self.refresh_employee_list()
                self.select_employee_by_name(name)
                if self.face_engine_callback:
                    self.face_engine_callback()
            else:
                messagebox.showerror("LỖI", "Không thể lưu nhân sự vào cơ sở dữ liệu!", parent=dlg)

        tk.Button(dlg, text="💾 LƯU HỒ SƠ NHÂN VIÊN", font=("Segoe UI", 10, "bold"),
                  bg="#059669", fg="white", activebackground="#047857", bd=0, pady=8,
                  cursor="hand2", command=save_new_employee).pack(fill=tk.X, padx=20)

    def open_edit_employee_dialog(self):
        """ Mở Form Sửa Thông Tin Nhân Viên Hiện Tại """
        selected = self.emp_listbox.get(tk.ACTIVE)
        if not selected:
            messagebox.showinfo("THÔNG BÁO", "Vui lòng chọn nhân viên cần chỉnh sửa từ danh sách!")
            return

        emp, _, _ = self.db.fetch_employee_profile(selected)
        if not emp:
            return

        old_name, old_role, old_img = emp

        dlg = tk.Toplevel(self)
        dlg.title(f"✏️ SỬA HỒ SƠ: {old_name}")
        dlg.geometry("450x380")
        dlg.configure(bg="#0b1329")
        dlg.transient(self)
        dlg.grab_set()

        new_image_path: list[str | None] = [None]

        tk.Label(dlg, text="HỌ VÀ TÊN NHÂN VIÊN:", font=("Segoe UI", 9, "bold"),
                 bg="#0b1329", fg="#38bdf8").pack(anchor="w", padx=20, pady=(15, 2))
        entry_name = tk.Entry(dlg, font=("Segoe UI", 10), bg="#1e293b", fg="white", insertbackground="white")
        entry_name.insert(0, old_name)
        entry_name.pack(fill=tk.X, padx=20, pady=(0, 10))

        tk.Label(dlg, text="CHỨC VỤ / VỊ TRÍ CÔNG TÁC:", font=("Segoe UI", 9, "bold"),
                 bg="#0b1329", fg="#38bdf8").pack(anchor="w", padx=20, pady=(0, 2))
        cb_role = ttk.Combobox(dlg, font=("Segoe UI", 10),
                               values=["Công nhân", "Kỹ sư công trường", "Giám sát an toàn EHS",
                                       "Chỉ huy trưởng", "Đội trưởng thi công", "Thầu phụ", "Bảo vệ"])
        cb_role.set(old_role)
        cb_role.pack(fill=tk.X, padx=20, pady=(0, 12))

        frame_img_select = tk.Frame(dlg, bg="#1e293b", bd=1, relief=tk.SOLID)
        frame_img_select.pack(fill=tk.X, padx=20, pady=(0, 15), ipady=6)

        lbl_img_preview = tk.Label(frame_img_select, text=f"Ảnh hiện tại: {os.path.basename(old_img)}",
                                   font=("Segoe UI", 8), bg="#1e293b", fg="#94a3b8")
        lbl_img_preview.pack(pady=4)

        btn_row = tk.Frame(frame_img_select, bg="#1e293b")
        btn_row.pack()

        def choose_new_file():
            fp = filedialog.askopenfilename(title="Chọn ảnh khuôn mặt mới",
                                            filetypes=[("Image Files", "*.jpg *.jpeg *.png")])
            if fp:
                new_image_path[0] = fp
                lbl_img_preview.config(text=f"✓ Ảnh mới: {os.path.basename(fp)}", fg="#34d399")

        def capture_new_photo():
            def on_captured(saved_path):
                new_image_path[0] = saved_path
                lbl_img_preview.config(text=f"✓ Đã chụp ảnh mới: {os.path.basename(saved_path)}", fg="#34d399")

            CameraCaptureWindow(dlg, get_frame_callback=self.get_frame_callback, on_captured_callback=on_captured)

        tk.Button(btn_row, text="📁 Chọn từ máy tính", font=("Segoe UI", 8, "bold"),
                  bg="#334155", fg="white", bd=0, padx=8, pady=3, cursor="hand2", command=choose_new_file).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_row, text="📷 Chụp từ Camera", font=("Segoe UI", 8, "bold"),
                  bg="#0284c7", fg="white", bd=0, padx=8, pady=3, cursor="hand2", command=capture_new_photo).pack(side=tk.LEFT, padx=4)

        def save_updated_employee():
            new_name = entry_name.get().strip()
            new_role = cb_role.get().strip() or "Công nhân"
            if not new_name:
                messagebox.showwarning("CẢNH BÁO", "Họ và Tên nhân viên không được để trống!", parent=dlg)
                return

            final_face_path = None
            if new_image_path[0] and os.path.exists(new_image_path[0]):
                dest_face = os.path.join("faces", f"{new_name}.jpg").replace("\\", "/")
                try:
                    shutil.copy(new_image_path[0], dest_face)
                    final_face_path = dest_face
                except Exception:
                    pass

            success = self.db.update_employee(old_name, new_name, new_role, final_face_path)
            if success:
                messagebox.showinfo("THÀNH CÔNG", f"Đã cập nhật hồ sơ: {new_name}", parent=dlg)
                dlg.destroy()
                self.refresh_employee_list()
                self.select_employee_by_name(new_name)
                if self.face_engine_callback:
                    self.face_engine_callback()
            else:
                messagebox.showerror("LỖI", "Không thể cập nhật nhân sự!", parent=dlg)

        tk.Button(dlg, text="💾 LƯU CẬP NHẬT", font=("Segoe UI", 10, "bold"),
                  bg="#2563eb", fg="white", activebackground="#1d4ed8", bd=0, pady=8,
                  cursor="hand2", command=save_updated_employee).pack(fill=tk.X, padx=20)

    def action_delete_employee(self):
        selected = self.emp_listbox.get(tk.ACTIVE)
        if not selected:
            messagebox.showinfo("THÔNG BÁO", "Vui lòng chọn nhân viên cần xóa!")
            return

        if messagebox.askyesno("XÁC NHẬN XÓA", f"Bạn có chắc chắn muốn xóa nhân viên '{selected}'?\nToàn bộ dữ liệu nhận diện khuôn mặt của nhân sự này sẽ bị gỡ bỏ."):
            self.db.delete_employee(selected)
            for ext in ['.jpg', '.jpeg', '.png']:
                img_path = os.path.join("faces", f"{selected}{ext}")
                if os.path.exists(img_path):
                    try:
                        os.remove(img_path)
                    except Exception:
                        pass
            self.refresh_employee_list()
            if self.face_engine_callback:
                self.face_engine_callback()
            messagebox.showinfo("HOÀN TẤT", f"Đã xóa thành công nhân viên: {selected}")

    def action_add_multiple_employees(self):
        file_paths = filedialog.askopenfilenames(
            title="Chọn 3-4 ảnh nhân viên (Tên file sẽ là Tên nhân sự)",
            filetypes=[("Image Files", "*.jpg *.jpeg *.png")]
        )
        if file_paths:
            count = 0
            for fp in file_paths:
                file_name = os.path.basename(fp)
                name = os.path.splitext(file_name)[0]
                dest_path = os.path.join("faces", f"{name}.jpg").replace("\\", "/")
                try:
                    shutil.copy(fp, dest_path)
                    self.db.add_employee(name, "Công nhân", dest_path)
                    count += 1
                except Exception:
                    pass

            messagebox.showinfo("THÀNH CÔNG", f"Đã nạp và tạo hồ sơ cho {count} nhân viên!")
            self.refresh_employee_list()
            if self.face_engine_callback:
                self.face_engine_callback()

    # =========================================================
    # LOGIC TAB 2: QUẢN LÝ HỒ SƠ NGƯỜI LẠ
    # =========================================================
    def refresh_strangers_list(self):
        for item in self.tree_strangers.get_children():
            self.tree_strangers.delete(item)

        strangers = self.db.fetch_all_strangers(limit=100)
        self.stranger_data_map = {}

        for st in strangers:
            st_id, timestamp, img_path, loc, ppe = st
            item_id = self.tree_strangers.insert("", tk.END, values=(st_id, timestamp, loc, ppe))
            self.stranger_data_map[item_id] = {
                'id': st_id,
                'time': timestamp,
                'img': img_path,
                'loc': loc,
                'ppe': ppe
            }

        # Reset preview
        self.lbl_st_img.config(image="", text="[Chọn một đối tượng]")
        self.lbl_st_time.config(text="Thời gian: ---")
        self.lbl_st_loc.config(text="Vị trí: ---")
        self.lbl_st_ppe.config(text="Trạng thái: ---")
        self.btn_convert_st.config(state=tk.DISABLED)
        self.btn_del_st.config(state=tk.DISABLED)

        # Chọn dòng đầu tiên nếu có
        children = self.tree_strangers.get_children()
        if children:
            self.tree_strangers.selection_set(children[0])
            self.tree_strangers.event_generate("<<TreeviewSelect>>")

    def on_stranger_select(self, event):
        selected = self.tree_strangers.selection()
        if selected:
            data = self.stranger_data_map.get(selected[0])
            if data:
                self.current_selected_stranger = data
                self.lbl_st_time.config(text=f"Thời gian: {data['time']}")
                self.lbl_st_loc.config(text=f"Vị trí: {data['loc']}")
                self.lbl_st_ppe.config(text=f"Trạng thái: {data['ppe']}")
                self.btn_convert_st.config(state=tk.NORMAL)
                self.btn_del_st.config(state=tk.NORMAL)

                # Nạp ảnh chân dung người lạ
                if data['img'] and os.path.exists(data['img']):
                    try:
                        pil_img = Image.open(data['img'])
                        w, h = pil_img.size
                        scale = min(280 / w, 210 / h)
                        nw = max(1, int(w * scale))
                        nh = max(1, int(h * scale))
                        resized_img = pil_img.resize((nw, nh), Image.Resampling.LANCZOS)
                        imgtk = ImageTk.PhotoImage(resized_img)
                        self.lbl_st_img.config(image=imgtk, text="")
                        self.stranger_imgtk = imgtk
                        setattr(self.lbl_st_img, 'image', imgtk)
                    except Exception:
                        self.lbl_st_img.config(image="", text="[Lỗi nạp ảnh]")
                else:
                    self.lbl_st_img.config(image="", text="[Ảnh không tồn tại]")

    def open_full_stranger_img(self, event=None):
        """ Mở ảnh người lạ độ phân giải gốc bằng trình xem ảnh mặc định của Windows """
        if hasattr(self, 'current_selected_stranger') and self.current_selected_stranger:
            st_img = self.current_selected_stranger.get('img')
            if st_img and os.path.exists(st_img):
                try:
                    os.startfile(st_img)
                except Exception as e:
                    print(f"Lỗi mở ảnh người lạ: {e}")

    def action_convert_current_stranger(self):
        """ Đăng ký người lạ đang chọn thành nhân viên chính thức """
        if not hasattr(self, 'current_selected_stranger') or not self.current_selected_stranger:
            return

        st = self.current_selected_stranger
        st_img = st['img']
        st_id = st['id']

        if not os.path.exists(st_img):
            messagebox.showerror("LỖI", "Tệp ảnh của người lạ này không tồn tại!")
            return

        top = tk.Toplevel(self)
        top.title("👤 ĐĂNG KÝ THÀNH NHÂN VIÊN CHÍNH THỨC")
        top.geometry("400x260")
        top.configure(bg="#0b1329")
        top.transient(self)
        top.grab_set()

        tk.Label(top, text="HỌ VÀ TÊN NHÂN VIÊN MỚI (*):", font=("Segoe UI", 9, "bold"),
                 bg="#0b1329", fg="#38bdf8").pack(anchor="w", padx=20, pady=(15, 2))
        entry_name = tk.Entry(top, font=("Segoe UI", 10), bg="#1e293b", fg="white", insertbackground="white")
        entry_name.pack(fill=tk.X, padx=20, pady=(0, 10))
        entry_name.focus_set()

        tk.Label(top, text="CHỨC VỤ / BỘ PHẬN:", font=("Segoe UI", 9, "bold"),
                 bg="#0b1329", fg="#38bdf8").pack(anchor="w", padx=20, pady=(0, 2))
        cb_role = ttk.Combobox(top, font=("Segoe UI", 10),
                               values=["Công nhân", "Kỹ sư công trường", "Giám sát an toàn EHS",
                                       "Chỉ huy trưởng", "Đội trưởng thi công", "Thầu phụ", "Bảo vệ"])
        cb_role.set("Công nhân")
        cb_role.pack(fill=tk.X, padx=20, pady=(0, 16))

        def execute_convert():
            name = entry_name.get().strip()
            role = cb_role.get().strip() or "Công nhân"
            if not name:
                messagebox.showwarning("CẢNH BÁO", "Vui lòng nhập Họ và Tên nhân viên!", parent=top)
                return

            dest_path = os.path.join("faces", f"{name}.jpg").replace("\\", "/")
            try:
                shutil.copy(st_img, dest_path)
            except Exception:
                pass

            self.db.add_employee(name, role, dest_path)
            self.db.delete_stranger(st_id)

            messagebox.showinfo("THÀNH CÔNG", f"Đã cấp hồ sơ nhân sự cho: {name} ({role})!", parent=top)
            top.destroy()

            self.refresh_employee_list()
            self.refresh_strangers_list()
            self.notebook.select(0)
            self.select_employee_by_name(name)

            if self.face_engine_callback:
                self.face_engine_callback()

        tk.Button(top, text="💾 HOÀN TẤT ĐĂNG KÝ", font=("Segoe UI", 10, "bold"),
                  bg="#059669", fg="white", activebackground="#047857", bd=0, pady=7,
                  cursor="hand2", command=execute_convert).pack(fill=tk.X, padx=20)

    def action_delete_current_stranger(self):
        if not hasattr(self, 'current_selected_stranger') or not self.current_selected_stranger:
            return

        st = self.current_selected_stranger
        if messagebox.askyesno("XÁC NHẬN", f"Bạn có chắc muốn xóa bản ghi người lạ ID #{st['id']}?"):
            self.db.delete_stranger(st['id'])
            self.refresh_strangers_list()

    def action_clear_all_strangers(self):
        if messagebox.askyesno("CẢNH BÁO", "Bạn có chắc chắn muốn xóa TOÀN BỘ lịch sử và ảnh người lạ trong hệ thống?\nHành động này không thể hoàn tác."):
            self.db.clear_all_strangers()
            self.refresh_strangers_list()
            messagebox.showinfo("HOÀN TẤT", "Đã xóa toàn bộ dữ liệu người lạ thành công!")