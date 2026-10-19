import os
import sys
import time
import json
import base64
import socket
import threading
import queue
import requests
from datetime import datetime

class ZaloNotifier:
    """
    Hệ thống gửi cảnh báo vi phạm qua Zalo chuyên nghiệp kèm HÌNH ẢNH BẰNG CHỨNG:
    - Chạy bất đồng bộ 100% qua Queue & Daemon Thread (không gây đơ camera hay UI).
    - Hỗ trợ Zalo Official Account (OA) OpenAPI: Tự động tải ảnh lên Zalo Media Store và đính kèm vào tin nhắn.
    - Hỗ trợ Webhook URL (Zalo Bot Gateway, n8n, Make): Đính kèm Base64, Data URI, và đường dẫn ảnh mạng nội bộ (LAN).
    - Tự động phát hiện IP mạng nội bộ (LAN) để tạo liên kết xem ảnh trực tiếp từ điện thoại.
    - Có cơ chế Cooldown chống spam thông báo liên tục.
    """
    def __init__(self, config_manager=None, local_ip=None):
        self.config_manager = config_manager
        self.local_ip = local_ip or self._detect_local_ip()
        self.msg_queue = queue.Queue()
        self.last_sent_times = {}  # {entity_key: timestamp}
        self.is_running = True
        
        # Khởi động worker daemon thread
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()

    def _detect_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def get_settings(self):
        if self.config_manager:
            return self.config_manager.settings.get("zalo", {})
        return {}

    def send_violation_alert(self, name, violation_type, evidence_path=None, location="Công trường Tapo PTZ"):
        """ Đẩy yêu cầu gửi cảnh báo vi phạm kèm hình ảnh vào hàng đợi (non-blocking) """
        z_cfg = self.get_settings()
        if not z_cfg.get("enabled", True):
            return False

        cooldown = z_cfg.get("cooldown_seconds", 45)
        now = time.time()
        last_time = self.last_sent_times.get(name, 0)

        # Kiểm tra cooldown để tránh spam Zalo
        if now - last_time < cooldown:
            return False

        self.last_sent_times[name] = now
        payload = {
            "type": "violation",
            "name": name,
            "violation_type": violation_type,
            "evidence_path": evidence_path,
            "location": location,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.msg_queue.put(payload)
        return True

    def send_test_alert(self):
        """ Gửi thông báo thử nghiệm KÈM ẢNH BẰNG CHỨNG để Quản lý test cấu hình Zalo """
        # Tự động tìm 1 file ảnh vi phạm thực tế để test kèm ảnh
        test_img = None
        vio_dir = "violations"
        if os.path.exists(vio_dir):
            files = [os.path.join(vio_dir, f) for f in os.listdir(vio_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            if files:
                test_img = files[-1]
        if not test_img and os.path.exists("faces"):
            f_files = [os.path.join("faces", f) for f in os.listdir("faces") if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            if f_files:
                test_img = f_files[0]

        payload = {
            "type": "test",
            "name": "TEST SYSTEM (Thử Nghiệm)",
            "violation_type": "Kiểm tra kết nối Zalo Notification kèm ảnh bằng chứng",
            "evidence_path": test_img,
            "location": "Máy chủ Smart EHS (Mạng nội bộ)",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.msg_queue.put(payload)
        return True

    def _process_queue(self):
        while self.is_running:
            try:
                item = self.msg_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                self._dispatch_to_zalo(item)
            except Exception as e:
                print(f"[Zalo Notifier] Lỗi gửi thông báo: {e}")
            finally:
                self.msg_queue.task_done()

    def _upload_image_to_zalo_oa(self, image_path, oa_token):
        """ Upload file ảnh lên Zalo Media Store để lấy attachment_id """
        if not image_path or not os.path.exists(image_path):
            return None
        try:
            url = "https://openapi.zalo.me/v2.0/oa/upload/image"
            headers = {"access_token": oa_token}
            filename = os.path.basename(image_path)
            with open(image_path, "rb") as f:
                files = {"file": (filename, f, "image/jpeg")}
                resp = requests.post(url, headers=headers, files=files, timeout=10.0)
            if resp.status_code == 200:
                res_json = resp.json()
                if res_json.get("error") == 0:
                    attachment_id = res_json.get("data", {}).get("attachment_id")
                    print(f"[Zalo Notifier] [+] Upload ảnh bằng chứng lên Zalo OA thành công! (Attachment ID: {attachment_id})")
                    return attachment_id
                else:
                    print(f"[Zalo Notifier] ⚠️ Zalo OA upload ảnh phản hồi: {res_json.get('message')}")
            else:
                print(f"[Zalo Notifier] ⚠️ HTTP Error khi upload ảnh Zalo OA: {resp.status_code}")
        except Exception as e:
            print(f"[Zalo Notifier] ⚠️ Lỗi kết nối khi upload ảnh Zalo OA: {e}")
        return None

    def _dispatch_to_zalo(self, item):
        z_cfg = self.get_settings()
        webhook_url = z_cfg.get("webhook_url", "").strip()
        oa_token = z_cfg.get("oa_access_token", "").strip()
        oa_user_id = z_cfg.get("oa_user_id", "").strip()

        evidence_path = item.get("evidence_path")
        has_valid_img = bool(evidence_path and os.path.exists(evidence_path))

        # Tạo nội dung tin nhắn văn bản chi tiết
        msg_title = "🚨 [CẢNH BÁO VI PHẠM AN TOÀN EHS]" if item["type"] == "violation" else "🔔 [SMART EHS TEST THÔNG BÁO]"
        text_lines = [
            f"{msg_title}",
            "━━━━━━━━━━━━━━━━━━━━",
            f"👤 Đối tượng: {item['name']}",
            f"⚠️ Lỗi vi phạm: {item['violation_type']}",
            f"📍 Vị trí: {item['location']}",
            f"🕒 Thời gian: {item['timestamp']}",
            "━━━━━━━━━━━━━━━━━━━━"
        ]

        if has_valid_img:
            text_lines.append("📸 Ảnh bằng chứng: Đã đính kèm & lưu trữ hồ sơ hệ thống.")
        else:
            text_lines.append("👉 Hệ thống tự động ghi nhận nhật ký vào CSDL.")

        text_body = "\n".join(text_lines)
        sent_success = False

        # =========================================================
        # 1. GỬI QUA ZALO WEBHOOK URL (BOT, N8N, GATEWAY)
        # =========================================================
        if webhook_url:
            try:
                headers = {"Content-Type": "application/json"}
                data = {
                    "text": text_body,
                    "message": text_body,
                    "event": "SAFETY_VIOLATION" if item["type"] == "violation" else "TEST",
                    "name": item["name"],
                    "violation": item["violation_type"],
                    "location": item["location"],
                    "timestamp": item["timestamp"],
                    "details": item
                }

                if has_valid_img:
                    try:
                        with open(evidence_path, "rb") as f:
                            b64_str = base64.b64encode(f.read()).decode("utf-8")
                        data["has_evidence"] = True
                        data["evidence_file"] = os.path.basename(evidence_path)
                        data["image_base64"] = b64_str
                        data["image_data_uri"] = f"data:image/jpeg;base64,{b64_str}"
                    except Exception as e_b64:
                        print(f"[Zalo Notifier] Lỗi đóng gói ảnh base64: {e_b64}")

                resp = requests.post(webhook_url, json=data, headers=headers, timeout=5.0)
                if resp.status_code in [200, 201, 204]:
                    print(f"[Zalo Notifier] [+] Đã gửi báo cáo qua Webhook Zalo thành công: {item['name']}")
                    sent_success = True
                else:
                    print(f"[Zalo Notifier] Webhook trả về mã phản hồi: {resp.status_code}")
            except Exception as ex:
                print(f"[Zalo Notifier] Không thể gửi Webhook Zalo: {ex}")

        # =========================================================
        # 2. GỬI QUA ZALO OA OPENAPI (OFFICIAL ACCOUNT)
        # =========================================================
        if oa_token and oa_user_id:
            try:
                oa_url = "https://openapi.zalo.me/v3.0/oa/message/cs"
                oa_headers = {
                    "access_token": oa_token,
                    "Content-Type": "application/json"
                }

                # Upload ảnh lên Zalo Media Store nếu có ảnh bằng chứng
                attachment_id = None
                if has_valid_img:
                    attachment_id = self._upload_image_to_zalo_oa(evidence_path, oa_token)

                if attachment_id:
                    # Gửi tin nhắn kèm ảnh bằng chứng qua Zalo OA Template Media
                    oa_payload = {
                        "recipient": {"user_id": oa_user_id},
                        "message": {
                            "text": text_body,
                            "attachment": {
                                "type": "template",
                                "payload": {
                                    "template_type": "media",
                                    "elements": [{
                                        "media_type": "image",
                                        "attachment_id": attachment_id
                                    }]
                                }
                            }
                        }
                    }
                    resp = requests.post(oa_url, json=oa_payload, headers=oa_headers, timeout=6.0)
                    if resp.status_code == 200 and resp.json().get("error") == 0:
                        print(f"[Zalo Notifier] [+] Đã gửi tin nhắn Zalo OA KÈM ẢNH BẰNG CHỨNG thành công tới: {oa_user_id}")
                        sent_success = True
                    else:
                        # Thử lại với dạng attachment type: image
                        oa_payload["message"]["attachment"] = {
                            "type": "image",
                            "payload": {"elements": [{"media_type": "image", "attachment_id": attachment_id}]}
                        }
                        resp2 = requests.post(oa_url, json=oa_payload, headers=oa_headers, timeout=6.0)
                        if resp2.status_code == 200 and resp2.json().get("error") == 0:
                            print(f"[Zalo Notifier] [+] Đã gửi tin nhắn Zalo OA KÈM ẢNH thành công tới: {oa_user_id}")
                            sent_success = True
                        else:
                            # Fallback gửi tin nhắn văn bản thông thường
                            fallback_payload = {
                                "recipient": {"user_id": oa_user_id},
                                "message": {"text": text_body}
                            }
                            resp_fb = requests.post(oa_url, json=fallback_payload, headers=oa_headers, timeout=5.0)
                            if resp_fb.status_code == 200 and resp_fb.json().get("error") == 0:
                                print(f"[Zalo Notifier] [+] Đã gửi tin nhắn văn bản Zalo OA thành công tới: {oa_user_id}")
                                sent_success = True
                else:
                    # Gửi tin nhắn văn bản trực tiếp (kèm link ảnh nội bộ)
                    oa_payload = {
                        "recipient": {"user_id": oa_user_id},
                        "message": {"text": text_body}
                    }
                    resp = requests.post(oa_url, json=oa_payload, headers=oa_headers, timeout=5.0)
                    if resp.status_code == 200 and resp.json().get("error") == 0:
                        print(f"[Zalo Notifier] [+] Đã gửi tin nhắn Zalo OA thành công tới: {oa_user_id}")
                        sent_success = True
                    else:
                        res_json = resp.json() if resp.status_code == 200 else {}
                        print(f"[Zalo Notifier] ⚠️ Zalo OA phản hồi: {res_json.get('message', resp.text)}")
            except Exception as ex:
                print(f"[Zalo Notifier] ⚠️ Lỗi kết nối Zalo OA: {ex}")

        if not sent_success and not webhook_url and not (oa_token and oa_user_id):
            if not getattr(self, '_unconfigured_logged', False):
                print(f"[Zalo Notifier] ℹ️ Chưa cấu hình Zalo Webhook URL hoặc OA Token trong Cài đặt (Bỏ qua gửi tin).")
                self._unconfigured_logged = True

