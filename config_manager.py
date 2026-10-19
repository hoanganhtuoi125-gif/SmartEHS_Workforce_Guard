import json
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    try:
        getattr(sys.stdout, 'reconfigure')(encoding='utf-8', errors='replace')
        getattr(sys.stderr, 'reconfigure')(encoding='utf-8', errors='replace')
    except Exception:
        pass

SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "beep_enabled": False,              # Tắt tiếng bíp cảnh báo (Mặc định tắt)
    "cameras": [
        {
            "id": "cam1",
            "name": "CAM 1 - Cổng Kiểm Soát (Webcam)",
            "type": "webcam",          # "webcam", "rtsp", hoặc "tapo"
            "source": 0,
            "role": "attendance"       # "attendance" (điểm danh/người lạ), "ppe" (bảo hộ), "general" (giám sát)
        }
    ],
    "camera": {
        "cam_attendance_type": "webcam",    # "webcam" hoặc "rtsp"
        "webcam_index": 0,
        "cam_attendance_rtsp": "",
        
        "tapo_ip": "",
        "tapo_user": "",
        "tapo_pass": "",
        "tapo_cloud_pass": "",
        "tapo_rtsp_port": 554,
        "tapo_onvif_port": 2020
    },
    "thresholds": {
        "ppe_confidence": 0.45,
        "face_similarity": 0.50,
        "cooldown_seconds": 30
    },
    "ppe_enabled": {
        "helmet": True,
        "vest": True,
        "gloves": False,
        "glasses": False,
        "boots": False
    },
    "colors": {
        "pass": "#00FF00",          # Xanh lá cho Đạt
        "violation": "#FF0000",     # Đỏ cho Vi phạm
        "unknown": "#FF8C00"        # Cam cho Unknown
    },
    "zalo": {
        "enabled": True,
        "webhook_url": "",
        "oa_access_token": "",
        "oa_user_id": "",
        "cooldown_seconds": 45
    },
    "telegram": {
        "enabled": True,
        "bot_token": "",
        "chat_id": "",
        "cooldown_seconds": 30
    },
    "voice": {
        "enabled": True,
        "stranger_enabled": True,   # Chỉ cảnh báo người lạ có thể bật/tắt
        "interval_seconds": 30,
        "voice_type": "vi-VN-HoaiMyNeural"
    }
}

class ConfigManager:
    def __init__(self, config_file=SETTINGS_FILE):
        self.config_file = config_file
        self.settings = self.load_settings()

    def _deep_merge(self, base, target):
        for k, v in base.items():
            if k not in target:
                target[k] = v
            elif isinstance(v, dict) and isinstance(target[k], dict):
                self._deep_merge(v, target[k])

    def load_settings(self):
        if not os.path.exists(self.config_file):
            self.save_settings(DEFAULT_SETTINGS)
            return DEFAULT_SETTINGS
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._deep_merge(DEFAULT_SETTINGS, data)
                return data
        except Exception as e:
            print(f" ⚠️ Lỗi đọc file settings.json, dùng cấu hình mặc định: {e}")
            return DEFAULT_SETTINGS

    def save_settings(self, new_settings=None):
        if new_settings is not None:
            self.settings = new_settings
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4, ensure_ascii=False)
            print(" [+] Đã lưu cấu hình mới vào settings.json thành công!")
            return True
        except Exception as e:
            print(f" ⚠️ Lỗi lưu file settings.json: {e}")
            return False

    def get_cameras(self):
        """ Lấy danh sách đa camera (tự động chuyển đổi nếu là định dạng cũ) """
        cams = self.settings.get("cameras")
        if cams and isinstance(cams, list) and len(cams) > 0:
            return cams

        # Fallback từ camera cũ nếu chưa có mảng cameras
        legacy = self.settings.get("camera", {})
        cam1_src = legacy.get("webcam_index", 0) if legacy.get("cam_attendance_type") == "webcam" else legacy.get("cam_attendance_rtsp", "")
        
        fallback_cams = [
            {
                "id": "cam1",
                "name": "CAM 1 - Cổng Kiểm Soát (Webcam)",
                "type": legacy.get("cam_attendance_type", "webcam"),
                "source": cam1_src if cam1_src != "" else 0,
                "role": "attendance"
            }
        ]
        self.settings["cameras"] = fallback_cams
        return fallback_cams

    def save_cameras(self, cameras_list):
        self.settings["cameras"] = cameras_list
        return self.save_settings()

    def hex_to_bgr(self, hex_color):
        """ Chuyển mã màu Hex (#RRGGBB) sang dạng Tuple BGR của OpenCV """
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6:
            return (0, 255, 0)
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return (b, g, r)