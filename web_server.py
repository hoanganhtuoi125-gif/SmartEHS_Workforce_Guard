import os
import sys
import time
import json
import threading
import cv2
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, Response, send_from_directory
from werkzeug.utils import secure_filename

from db_manager import AttendanceDatabase
from config_manager import ConfigManager
from zalo_notifier import ZaloNotifier
from voice_notifier import VoiceNotifier

if hasattr(sys.stdout, 'reconfigure'):
    try:
        getattr(sys.stdout, 'reconfigure')(encoding='utf-8', errors='replace')
        getattr(sys.stderr, 'reconfigure')(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Khởi tạo Flask App (Hỗ trợ cả môi trường script và đóng gói .exe PyInstaller)
_base_web = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, 'frozen', False):
    _exe_dir = os.path.dirname(sys.executable)
    if os.path.exists(os.path.join(_exe_dir, "web", "templates")):
        _base_web = _exe_dir
    else:
        _meipass = getattr(sys, '_MEIPASS', os.path.join(_exe_dir, '_internal'))
        if os.path.exists(os.path.join(_meipass, "web", "templates")):
            _base_web = _meipass

app = Flask(
    __name__,
    template_folder=os.path.join(_base_web, "web", "templates"),
    static_folder=os.path.join(_base_web, "web", "static")
)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

# Biến toàn cục hệ thống
db = AttendanceDatabase()
config_mgr = ConfigManager()
zalo_notifier = ZaloNotifier(config_mgr)
voice_notifier = VoiceNotifier(config_mgr)
face_reload_callback = None

# Quản lý bộ đệm Stream Video Web (MJPEG)
frame_lock = threading.Lock()
stream_frames = {
    "cam1": None,  # bytes JPEG
    "cam2": None   # bytes JPEG
}

def update_web_stream_frame(cam_id, bgr_frame):
    """ Cập nhật frame hình ảnh từ OpenCV để phục vụ Live Stream trên Web """
    if bgr_frame is None:
        return
    try:
        # Resize nhẹ 640x360 cho web stream để cực kỳ tiết kiệm CPU/băng thông
        h, w = bgr_frame.shape[:2]
        target_w = 640
        target_h = int(h * (640 / w))
        small = cv2.resize(bgr_frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
        # Nén JPEG chất lượng 70%
        _, jpeg = cv2.imencode('.jpg', small, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        with frame_lock:
            stream_frames[cam_id] = jpeg.tobytes()
    except Exception:
        pass

def generate_mjpeg(cam_id):
    """ Bộ phát MJPEG stream mượt mà cho trình duyệt """
    blank_frame = None
    while True:
        with frame_lock:
            frame_bytes = stream_frames.get(cam_id)
        
        if frame_bytes is None:
            # Tạo frame đen báo hiệu camera đang khởi động nếu chưa có dữ liệu
            if blank_frame is None:
                img = np.zeros((360, 640, 3), dtype=np.uint8)
                cv2.putText(img, f"SMART EHS - {cam_id.upper()} CONNECTING...", (120, 180),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (100, 150, 255), 2)
                _, jpeg = cv2.imencode('.jpg', img)
                blank_frame = jpeg.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + blank_frame + b'\r\n')
            time.sleep(0.5)
        else:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.04)  # ~25 FPS

# =========================================================
# ROUTES CHÍNH & MEDIA
# =========================================================

@app.route('/')
def route_index():
    return render_template('index.html')

@app.route('/stream/<cam_id>')
def route_stream(cam_id):
    return Response(generate_mjpeg(cam_id), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/media/<path:filename>')
def route_media(filename):
    """ Phục vụ an toàn các ảnh từ thư mục faces, violations, strangers """
    base_dir = os.path.dirname(__file__)
    safe_path = os.path.normpath(os.path.join(base_dir, filename))
    # Kiểm tra bảo mật path traversal
    if not safe_path.startswith(base_dir):
        return "Truy cập bị từ chối", 403
    if not os.path.exists(safe_path):
        return "Ảnh không tồn tại", 404
    dir_name = os.path.dirname(safe_path)
    base_name = os.path.basename(safe_path)
    return send_from_directory(dir_name, base_name)

# =========================================================
# API THỐNG KÊ DASHBOARD & BÁO CÁO
# =========================================================

@app.route('/api/stats')
def api_stats():
    att_c, vio_c, str_c = db.get_today_stats()
    employees = db.fetch_all_employees()
    recent_viols = db.fetch_recent_violations(limit=6)
    recent_logs = db.fetch_recent_logs(limit=6)
    recent_strangers = db.fetch_all_strangers(limit=6)

    # Định dạng vi phạm gần nhất
    formatted_viols = []
    for v in recent_viols:
        formatted_viols.append({
            "name": v[0],
            "time": v[1],
            "violation": v[2],
            "evidence_image": v[3].replace("\\", "/") if v[3] else None,
            "avatar": v[4].replace("\\", "/") if v[4] else None
        })

    # Định dạng người lạ gần nhất
    formatted_strangers = []
    for s in recent_strangers:
        formatted_strangers.append({
            "id": s[0],
            "time": s[1],
            "image": s[2].replace("\\", "/") if s[2] else None,
            "location": s[3],
            "ppe": s[4]
        })

    return jsonify({
        "status": "success",
        "attendance_count": att_c,
        "violation_count": vio_c,
        "stranger_count": str_c,
        "employee_count": len(employees),
        "recent_violations": formatted_viols,
        "recent_logs": recent_logs,
        "recent_strangers": formatted_strangers,
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

@app.route('/api/export-excel')
def api_export_excel():
    success, path_or_err = db.export_to_excel()
    if success and os.path.exists(path_or_err):
        return send_file(path_or_err, as_attachment=True, download_name="Bao_Cao_Diem_Danh_PPE.xlsx")
    return jsonify({"status": "error", "message": path_or_err}), 500

# =========================================================
# API QUẢN LÝ NHÂN SỰ (THÊM, SỬA, XÓA, XEM CHI TIẾT)
# =========================================================

@app.route('/api/employees', methods=['GET'])
def api_get_employees():
    employees = db.fetch_all_employees()
    result = []
    for emp in employees:
        name, role, img_path = emp
        # Lấy số lượt điểm danh & vi phạm
        _, att_logs, vio_logs = db.fetch_employee_profile(name)
        result.append({
            "name": name,
            "role": role,
            "image_path": img_path.replace("\\", "/") if img_path else None,
            "att_count": len(att_logs),
            "vio_count": len(vio_logs)
        })
    return jsonify({"status": "success", "data": result})

@app.route('/api/employees', methods=['POST'])
def api_add_employee():
    name = request.form.get('name', '').strip()
    role = request.form.get('role', 'Công nhân').strip()
    file = request.files.get('image')

    if not name:
        return jsonify({"status": "error", "message": "Vui lòng nhập họ và tên nhân viên!"}), 400
    if not file or not file.filename:
        return jsonify({"status": "error", "message": "Vui lòng chọn ảnh khuôn mặt nhận diện!"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.jpg', '.jpeg', '.png']:
        return jsonify({"status": "error", "message": "Chỉ chấp nhận file ảnh (.jpg, .jpeg, .png)!"}), 400

    faces_dir = "faces"
    os.makedirs(faces_dir, exist_ok=True)
    clean_name = secure_filename(name) or "emp"
    saved_path = os.path.join(faces_dir, f"{name}{ext}").replace("\\", "/")

    file.save(saved_path)
    ok = db.add_employee(name, role, saved_path)
    if ok:
        if face_reload_callback:
            try:
                face_reload_callback()
            except Exception as e:
                print(f"[Web] Reload Face Engine lỗi: {e}")
        return jsonify({"status": "success", "message": f"Đã thêm nhân viên {name} thành công!"})
    else:
        return jsonify({"status": "error", "message": "Tên nhân viên đã tồn tại hoặc có lỗi cơ sở dữ liệu!"}), 400

@app.route('/api/employees/<name>', methods=['GET'])
def api_get_employee_detail(name):
    emp, att_logs, vio_logs = db.fetch_employee_profile(name)
    if not emp:
        return jsonify({"status": "error", "message": "Không tìm thấy nhân sự"}), 404

    formatted_att = [{"time": a[0], "ppe": a[1]} for a in att_logs]
    formatted_vio = [{
        "time": v[0],
        "violation": v[1],
        "evidence_image": v[2].replace("\\", "/") if v[2] else None
    } for v in vio_logs]

    return jsonify({
        "status": "success",
        "name": emp[0],
        "role": emp[1],
        "image_path": emp[2].replace("\\", "/") if emp[2] else None,
        "attendance_logs": formatted_att,
        "violation_logs": formatted_vio
    })

@app.route('/api/employees/<name>', methods=['PUT'])
def api_update_employee(name):
    new_name = request.form.get('new_name', name).strip()
    new_role = request.form.get('new_role', 'Công nhân').strip()
    file = request.files.get('image')

    new_img_path = None
    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png']:
            new_img_path = os.path.join("faces", f"{new_name}{ext}").replace("\\", "/")
            file.save(new_img_path)

    ok = db.update_employee(name, new_name, new_role, new_img_path)
    if ok:
        if face_reload_callback:
            try:
                face_reload_callback()
            except Exception:
                pass
        return jsonify({"status": "success", "message": f"Đã cập nhật hồ sơ nhân sự {new_name}!"})
    return jsonify({"status": "error", "message": "Không thể cập nhật hồ sơ!"}), 400

@app.route('/api/employees/<name>', methods=['DELETE'])
def api_delete_employee(name):
    ok = db.delete_employee(name)
    # Xóa file ảnh trong thư mục faces
    for ext in ['.jpg', '.jpeg', '.png']:
        fpath = os.path.join("faces", f"{name}{ext}")
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass
    if ok:
        if face_reload_callback:
            try:
                face_reload_callback()
            except Exception:
                pass
        return jsonify({"status": "success", "message": f"Đã xóa nhân viên {name}!"})
    return jsonify({"status": "error", "message": "Không thể xóa nhân viên!"}), 400

# =========================================================
# API QUẢN LÝ NGƯỜI LẠ (STRANGERS)
# =========================================================

@app.route('/api/strangers', methods=['GET'])
def api_get_strangers():
    rows = db.fetch_all_strangers(limit=100)
    data = []
    for r in rows:
        data.append({
            "id": r[0],
            "time": r[1],
            "image_path": r[2].replace("\\", "/") if r[2] else None,
            "location": r[3],
            "ppe_status": r[4]
        })
    return jsonify({"status": "success", "data": data})

@app.route('/api/strangers/<int:stranger_id>', methods=['DELETE'])
def api_delete_stranger(stranger_id):
    ok = db.delete_stranger(stranger_id)
    if ok:
        return jsonify({"status": "success", "message": "Đã xóa đối tượng người lạ!"})
    return jsonify({"status": "error", "message": "Không thể xóa đối tượng!"}), 400

@app.route('/api/strangers', methods=['DELETE'])
def api_clear_strangers():
    ok = db.clear_all_strangers()
    if ok:
        return jsonify({"status": "success", "message": "Đã dọn dẹp sạch toàn bộ hồ sơ người lạ!"})
    return jsonify({"status": "error", "message": "Có lỗi khi dọn dẹp!"}), 500

@app.route('/api/strangers/<int:stranger_id>/convert', methods=['POST'])
def api_convert_stranger(stranger_id):
    """ Chuyển người lạ thành nhân viên chính thức từ Web """
    name = request.json.get('name', '').strip()
    role = request.json.get('role', 'Công nhân').strip()

    if not name:
        return jsonify({"status": "error", "message": "Vui lòng nhập tên cho nhân viên mới!"}), 400

    # Lấy thông tin người lạ
    rows = db.fetch_all_strangers(limit=200)
    target = None
    for r in rows:
        if r[0] == stranger_id:
            target = r
            break

    if not target:
        return jsonify({"status": "error", "message": "Không tìm thấy hồ sơ người lạ!"}), 404

    old_img_path = target[2]
    faces_dir = "faces"
    os.makedirs(faces_dir, exist_ok=True)
    new_img_path = os.path.join(faces_dir, f"{name}.jpg").replace("\\", "/")

    if old_img_path and os.path.exists(old_img_path):
        import shutil
        shutil.copy(old_img_path, new_img_path)
    else:
        return jsonify({"status": "error", "message": "File ảnh người lạ không còn tồn tại trên đĩa!"}), 400

    ok = db.add_employee(name, role, new_img_path)
    if ok:
        db.delete_stranger(stranger_id)
        if face_reload_callback:
            try:
                face_reload_callback()
            except Exception:
                pass
        return jsonify({"status": "success", "message": f"Đã chuyển đổi thành công {name} thành nhân viên chính thức!"})
    return jsonify({"status": "error", "message": "Không thể thêm nhân viên mới (có thể trùng tên)!"}), 400

# =========================================================
# API VI PHẠM & CÀI ĐẶT & ZALO
# =========================================================

@app.route('/api/violations', methods=['GET'])
def api_get_violations():
    rows = db.fetch_all_violations(limit=100)
    data = []
    for r in rows:
        data.append({
            "id": r[0],
            "name": r[1],
            "time": r[2],
            "violation": r[3],
            "evidence_image": r[4].replace("\\", "/") if r[4] else None,
            "avatar": r[5].replace("\\", "/") if r[5] else None
        })
    return jsonify({"status": "success", "data": data})

@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    return jsonify(config_mgr.settings)

@app.route('/api/settings', methods=['POST'])
def api_save_settings():
    new_data = request.json
    if not new_data:
        return jsonify({"status": "error", "message": "Dữ liệu cấu hình không hợp lệ"}), 400
    config_mgr.save_settings(new_data)
    return jsonify({"status": "success", "message": "Đã lưu cài đặt mới thành công!"})

@app.route('/api/zalo/test', methods=['POST'])
def api_test_zalo():
    ok = zalo_notifier.send_test_alert()
    if ok:
        return jsonify({"status": "success", "message": "Đã đẩy tin nhắn thử nghiệm vào hàng đợi gửi Zalo!"})
    return jsonify({"status": "error", "message": "Không thể gửi tin nhắn thử nghiệm!"}), 500

@app.route('/api/voice/test', methods=['POST'])
def api_test_voice():
    ok = voice_notifier.test_speak()
    if ok:
        return jsonify({"status": "success", "message": "Đang phát giọng đọc thử nghiệm qua loa máy chủ!"})
    return jsonify({"status": "error", "message": "Hệ thống đang phát cảnh báo khác, vui lòng thử lại sau ít giây!"}), 429

@app.route('/api/voice/toggle', methods=['POST'])
def api_toggle_voice():
    cur = config_mgr.settings.get("voice", {}).get("enabled", True)
    new_state = not cur
    config_mgr.settings.setdefault("voice", {})["enabled"] = new_state
    config_mgr.save_settings()
    state_str = "bật" if new_state else "tắt"
    return jsonify({"status": "success", "enabled": new_state, "message": f"Đã {state_str} cảnh báo giọng nói thành công."})


# =========================================================
# KHỞI CHẠY TIẾN TRÌNH WEB SERVER
# =========================================================

def start_web_server_background(db_instance=None, config_instance=None, face_callback=None, voice_instance=None, port=5000):
    """ Khởi chạy Flask Server trong Daemon Thread để tích hợp mượt mà vào ứng dụng chính """
    global db, config_mgr, zalo_notifier, voice_notifier, face_reload_callback
    if db_instance:
        db = db_instance
    if config_instance:
        config_mgr = config_instance
        zalo_notifier = ZaloNotifier(config_mgr)
        if not voice_instance:
            voice_notifier = VoiceNotifier(config_mgr)
    if voice_instance:
        voice_notifier = voice_instance
    if face_callback:
        face_reload_callback = face_callback

    def run_app():
        # Tắt bớt log debug của werkzeug để console sạch sẽ
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        print(f" [+] 🌐 SMART EHS Web Portal đang khởi chạy tại: http://0.0.0.0:{port}")
        app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)

    server_thread = threading.Thread(target=run_app, daemon=True)
    server_thread.start()
    return server_thread

if __name__ == '__main__':
    print("[-] Khởi chạy Smart EHS Web Portal độc lập...")
    app.run(host='0.0.0.0', port=5000, debug=True)
