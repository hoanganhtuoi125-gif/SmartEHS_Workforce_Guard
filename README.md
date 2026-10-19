# 🛡️ SmartEHS Workforce Guard

> **Hệ thống AI Giám sát An toàn Lao động (PPE) & Điểm danh Nhân sự Đa Camera Công Trường**

![SmartEHS Banner](Hinh_2_1_Kien_Truc_5_Tang_SmartEHS_Gon.png)

---

## 🌟 Giới Thiệu

**SmartEHS Workforce Guard** là giải pháp ứng dụng Trí tuệ Nhân tạo (AI Vision) toàn diện nhằm tự động hóa công tác giám sát an toàn lao động và quản lý nhân sự tại hiện trường công trường xây dựng hoặc nhà máy sản xuất.

Hệ thống kết hợp đồng thời mô hình phát hiện trang thiết bị bảo hộ lao động (**PPE Detection - YOLO**) và nhận diện khuôn mặt (**InsightFace**) để kiểm soát tuân thủ an toàn theo thời gian thực mà không làm gián đoạn luồng làm việc.

---

## 🚀 Tính Năng Nổi Bật

- **📹 Quản lý Đa Camera Linh Hoạt (Multi-Camera Grid):**
  - Hỗ trợ cùng lúc nhiều nguồn video: Webcam USB, Camera IP chuẩn RTSP, và Camera Tapo PTZ thông minh.
  - Tự động bố trí lưới hiển thị tối ưu tài nguyên CPU/GPU (Zero-Lag Reconnect).

- **🦺 Giám sát Vi phạm Bảo hộ Lao động (PPE):**
  - Quét và phát hiện các vi phạm an toàn: Không đội mũ bảo hộ, không mặc áo phản quang, thiếu găng tay, kính bảo hộ, v.v.
  - Cơ chế **Cooldown** thông minh chống spam cảnh báo lặp lại.

- **👤 Điểm danh & Nhận diện Người lạ (Face Recognition):**
  - Tự động điểm danh nhân sự đã đăng ký hồ sơ khuôn mặt.
  - Phát hiện và phát cảnh báo tức thì khi người lạ chưa đăng ký xuất hiện tại khu vực kiểm soát.

- **🎙️ Đàm thoại Trực tiếp & Điều khiển PTZ (Tapo/RTSP):**
  - Bàn điều khiển xoay camera 360 độ (Pan/Tilt) qua giao thức ONVIF.
  - Tính năng **Push-to-Talk**: Nói trực tiếp từ mic máy tính phát ra loa camera hiện trường (Talkback qua Go2RTC).

- **🔔 Thông báo Vi phạm Tức thời:**
  - Tự động gửi ảnh bằng chứng và vị trí vi phạm qua **Telegram Bot** và **Zalo Webhook**.
  - Phát cảnh báo bằng giọng nói tiếng Việt tự nhiên (TTS) khi có người lạ hoặc sự cố.

- **📊 Báo cáo & Quản lý Toàn diện:**
  - Xuất báo cáo điểm danh và lịch sử vi phạm chi tiết ra file **Excel (.xlsx)**.
  - Tích hợp **Web Portal Dashboard** truy cập qua trình duyệt máy tính hoặc điện thoại di động trong mạng LAN.

---

## 🛠️ Yêu Cầu Hệ Thống & Cài Đặt

### 1. Yêu Cầu Tiên Quyết
- Hệ điều hành: Windows 10 / 11 (64-bit).
- Python: Phiên bản **3.10** hoặc **3.11**.
- Card đồ họa rời NVIDIA (khuyên dùng để tăng tốc độ xử lý GPU CUDA, hoặc CPU đa nhân).

### 2. Cài Đặt Môi Trường

```bash
# 1. Clone dự án về máy
git clone <URL_REPO_CUA_BAN>
cd SmartEHS_Workforce_Guard

# 2. Khởi tạo và kích hoạt môi trường ảo (Khuyên dùng)
python -m venv venv
venv\Scripts\activate

# 3. Cài đặt các thư viện phụ thuộc
pip install -r requirements.txt
```

---

## 💻 Hướng Dẫn Khởi Chạy

### Cách 1: Chạy trực tiếp từ mã nguồn Python
```bash
python main.py
```
*Hoặc nhấp đúp vào file `Chay_App_Python.bat`.*

### Cách 2: Truy cập Web Dashboard Quản trị
Khi ứng dụng đang chạy, mở trình duyệt và truy cập:
- Trên máy chủ: `http://localhost:5000`
- Từ thiết bị khác cùng mạng LAN: `http://[IP_MAY_TINH]:5000`

---

## ⚙️ Cấu Hình Hệ Thống

1. Bấm nút **⚙️ CÀI ĐẶT ĐA CAMERA & HỆ THỐNG** trên giao diện chính.
2. Thêm hoặc tùy chỉnh camera:
   - **Webcam**: Chọn chỉ số cổng USB (0, 1, ...).
   - **Camera RTSP**: Nhập đường dẫn luồng RTSP (ví dụ: `rtsp://user:pass@192.168.1.100:554/stream1`).
   - **Tapo PTZ**: Nhập IP, tài khoản camera và mật khẩu App Tapo để kích hoạt loa/xoay.
3. Cấu hình nhận thông báo vi phạm:
   - **Telegram**: Nhập Bot Token (tạo từ `@BotFather`) và Chat ID của bạn/nhóm.
   - **Zalo**: Nhập Zalo Webhook URL hoặc OA Access Token.

---

## 📂 Cấu Trúc Thư Mục Dự Án

```
SmartEHS_Workforce_Guard/
├── main.py                     # Điểm khởi chạy ứng dụng chính
├── main_app_dual_cam.py        # Giao diện giám sát Tkinter & vòng lặp AI chính
├── pytorch_engine.py           # Engine xử lý mô hình phát hiện bảo hộ PPE (YOLO)
├── face_engine.py              # Engine nhận diện khuôn mặt nhân viên (InsightFace)
├── db_manager.py               # Quản lý cơ sở dữ liệu SQLite & xuất file Excel
├── settings_dialog.py          # Hộp thoại cài đặt đa camera, ngưỡng AI & thông báo
├── employee_manager_dialog.py  # Hộp thoại quản lý hồ sơ nhân sự & chụp ảnh khuôn mặt
├── telegram_notifier.py        # Module gửi ảnh & tin nhắn cảnh báo qua Telegram Bot
├── zalo_notifier.py            # Module gửi thông báo qua Zalo Webhook / OA
├── voice_notifier.py           # Module phát âm thanh & giọng nói cảnh báo an ninh
├── talkback_streamer.py        # Module xử lý đàm thoại 2 chiều qua loa camera
├── ui_renderer.py              # Vẽ bounding box và huy hiệu trạng thái tiếng Việt
├── web_server.py               # Máy chủ Web Flask cung cấp Dashboard trực tuyến
├── config_manager.py           # Quản lý đọc/lưu file cấu hình settings.json
├── models/                     # Trọng số mô hình AI (.pt / .onnx)
├── web/                        # Giao diện Web Dashboard (HTML/CSS/JS)
├── settings.json               # File cấu hình hoạt động của hệ thống
└── requirements.txt            # Danh sách thư viện Python cần thiết
```

---

## 📄 Bản Quyền & Giấy Phép
Dự án được phát triển phục vụ mục đích nghiên cứu, học tập và ứng dụng thực tiễn trong công tác an toàn lao động tại công trường.
