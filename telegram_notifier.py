import os
import time
import queue
import threading
import requests
from datetime import datetime

class TelegramNotifier:
    """
    Hệ thống gửi cảnh báo vi phạm an toàn qua Telegram Bot KÈM HÌNH ẢNH BẰNG CHỨNG:
    - Chạy bất đồng bộ 100% qua hàng đợi (Queue) & Daemon Thread (không giật lag camera).
    - Sử dụng Telegram Bot API chính thức (https://api.telegram.org), miễn phí vĩnh viễn 100%.
    - Hỗ trợ gửi trực tiếp tới Chat cá nhân hoặc Nhóm Ban Chỉ Huy công trường.
    - Tự động đính kèm ảnh chụp hiện trường vi phạm / khuôn mặt người lạ sắc nét.
    - Có cơ chế Cooldown chống spam thông báo liên tục.
    """
    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        self.msg_queue = queue.Queue()
        self.last_sent_times = {}  # {entity_key: timestamp}
        self.is_running = True

        # Khởi động worker daemon thread
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()

    def get_settings(self):
        if self.config_manager:
            return self.config_manager.settings.get("telegram", {})
        return {}

    def send_violation_alert(self, name, violation_type, evidence_path=None, location="Công trường Tapo PTZ"):
        """ Đẩy yêu cầu gửi cảnh báo vi phạm kèm ảnh vào hàng đợi bất đồng bộ """
        t_cfg = self.get_settings()
        if not t_cfg.get("enabled", True):
            return False

        bot_token = t_cfg.get("bot_token", "").strip()
        chat_id = t_cfg.get("chat_id", "").strip()
        if not bot_token or not chat_id:
            return False

        cooldown = t_cfg.get("cooldown_seconds", 30)
        now = time.time()
        last_time = self.last_sent_times.get(name, 0)

        # Kiểm tra cooldown để tránh spam
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
        """ Gửi thông báo thử nghiệm kèm ảnh để kiểm tra cấu hình Telegram """
        t_cfg = self.get_settings()
        bot_token = t_cfg.get("bot_token", "").strip()
        chat_id = t_cfg.get("chat_id", "").strip()

        if not bot_token or not chat_id:
            return False, "Chưa điền Bot Token hoặc Chat ID trong Cài đặt!"

        # Tìm 1 file ảnh thực tế để test kèm ảnh
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
            "violation_type": "Kiểm tra kết nối Telegram Bot thành công!",
            "evidence_path": test_img,
            "location": "Máy chủ Smart EHS AI",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # Gửi trực tiếp đồng bộ để trả về kết quả ngay cho người dùng
        return self._send_to_telegram(payload, bot_token, chat_id)

    def _process_queue(self):
        """ Vòng lặp lấy thông báo từ hàng đợi và gửi đi """
        while self.is_running:
            try:
                item = self.msg_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                t_cfg = self.get_settings()
                bot_token = t_cfg.get("bot_token", "").strip()
                chat_id = t_cfg.get("chat_id", "").strip()
                if bot_token and chat_id:
                    self._send_to_telegram(item, bot_token, chat_id)
            except Exception as e:
                print(f"[Telegram Notifier] Lỗi xử lý gửi: {e}")
            finally:
                self.msg_queue.task_done()

    def _send_to_telegram(self, item, bot_token, chat_id):
        """ Gửi tin nhắn kèm ảnh bằng chứng trực tiếp qua Telegram Bot API """
        evidence_path = item.get("evidence_path")
        has_valid_img = bool(evidence_path and os.path.exists(evidence_path))
        photo_bytes = None
        if has_valid_img:
            try:
                with open(evidence_path, "rb") as pf:
                    photo_bytes = pf.read()
            except Exception as e:
                print(f"[Telegram Notifier] Không thể đọc file ảnh {evidence_path}: {e}")
                has_valid_img = False

        msg_title = "🚨 <b>[CẢNH BÁO VI PHẠM AN TOÀN EHS]</b>" if item["type"] == "violation" else "🔔 <b>[SMART EHS TEST THÀNH CÔNG]</b>"
        caption = (
            f"{msg_title}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Đối tượng:</b> {item['name']}\n"
            f"⚠️ <b>Lỗi vi phạm:</b> <code>{item['violation_type']}</code>\n"
            f"📍 <b>Vị trí:</b> {item['location']}\n"
            f"🕒 <b>Thời gian:</b> {item['timestamp']}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👉 <i>Hệ thống tự động lưu trữ bằng chứng & CSDL.</i>"
        )

        clean_id = str(chat_id).strip()
        candidates = [clean_id]
        if clean_id.startswith("-") and not clean_id.startswith("-100"):
            candidates.append(f"-100{clean_id.lstrip('-')}")
        elif not clean_id.startswith("-"):
            candidates.append(f"-100{clean_id}")
            candidates.append(f"-{clean_id}")

        last_err = ""
        for cid in candidates:
            try:
                # 1. Nếu có ảnh bằng chứng: Gửi qua sendPhoto kèm Caption
                if has_valid_img and photo_bytes:
                    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                    files = {"photo": ("evidence.jpg", photo_bytes, "image/jpeg")}
                    data = {
                        "chat_id": cid,
                        "caption": caption,
                        "parse_mode": "HTML"
                    }
                    resp = requests.post(url, data=data, files=files, timeout=12.0)
                # 2. Nếu không có ảnh: Gửi tin nhắn văn bản qua sendMessage
                else:
                    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                    data = {
                        "chat_id": cid,
                        "text": caption,
                        "parse_mode": "HTML"
                    }
                    resp = requests.post(url, json=data, timeout=8.0)

                res_json = resp.json() if resp.status_code == 200 else {}
                if resp.status_code == 200 and res_json.get("ok"):
                    print(f"[Telegram Notifier] [+] Đã gửi cảnh báo Telegram thành công tới {cid}: {item['name']}")
                    return True, f"✅ Đã gửi tin nhắn và ảnh bằng chứng qua Telegram thành công (ID: {cid})!"
                else:
                    desc = res_json.get("description", resp.text)
                    last_err = f"Telegram API từ chối ({resp.status_code}): {desc}"
                    err_lower = desc.lower()
                    if any(k in err_lower for k in ["chat not found", "migrated", "supergroup", "peer_id_invalid", "chat_id is empty"]):
                        continue
                    else:
                        return False, last_err
            except requests.exceptions.Timeout:
                last_err = "Hết thời gian chờ kết nối tới máy chủ Telegram (Timeout)."
            except Exception as ex:
                last_err = f"Lỗi kết nối Telegram: {ex}"

        if "chat not found" in last_err.lower():
            last_err = (
                "⚠️ Lỗi Telegram: 'Chat not found' (Chưa tìm thấy nhóm hoặc cuộc trò chuyện).\n\n"
                "👉 NGUYÊN NHÂN & CÁCH XỬ LÝ (Rất đơn giản):\n"
                "Telegram bảo mật không cho Bot tự nhắn tin vào nhóm nếu Bot chưa được thêm vào.\n\n"
                "BẠN HÃY LÀM THEO 2 BƯỚC:\n"
                "1. Vào nhóm Telegram của bạn -> Bấm Thêm thành viên (Add Members) -> Gõ tìm bot và THÊM VÀO NHÓM.\n"
                "2. Gửi 1 tin nhắn bất kỳ vào nhóm (ví dụ: 'hello bot').\n"
                "(Hoặc nếu muốn nhận riêng: Mở chat riêng với Bot trên Telegram và bấm START).\n\n"
                "Sau đó bấm nút TEST lại là thành công ngay!"
            )
        return False, last_err

    @staticmethod
    def detect_chat_id(bot_token):
        """
        Tự động truy vấn getUpdates từ Telegram API để phát hiện Chat ID mới nhất
        khi người dùng đã thêm Bot vào nhóm hoặc đã nhắn tin cho Bot.
        """
        if not bot_token:
            return None, "Vui lòng nhập Bot Token trước!"
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
            resp = requests.get(url, timeout=7.0)
            if resp.status_code != 200:
                return None, f"Không thể kết nối Telegram API ({resp.status_code})"
            data = resp.json()
            if not data.get("ok"):
                return None, data.get("description", "Lỗi Telegram getUpdates")

            updates = data.get("result", [])
            if not updates:
                return None, (
                    "Chưa tìm thấy tương tác nào với Bot!\n\n"
                    "👉 Vui lòng:\n"
                    "1. Vào nhóm Telegram -> Thêm bot vào nhóm\n"
                    "2. Gửi 1 tin nhắn bất kỳ vào nhóm\n"
                    "(hoặc nhắn /start cho bot trong chat riêng)\n"
                    "3. Sau đó bấm lại nút 'Tự Động Tìm ID'."
                )

            for upd in reversed(updates):
                chat = None
                if "message" in upd and "chat" in upd["message"]:
                    chat = upd["message"]["chat"]
                elif "my_chat_member" in upd and "chat" in upd["my_chat_member"]:
                    chat = upd["my_chat_member"]["chat"]
                elif "channel_post" in upd and "chat" in upd["channel_post"]:
                    chat = upd["channel_post"]["chat"]

                if chat and "id" in chat:
                    cid = str(chat["id"])
                    title = chat.get("title") or chat.get("username") or chat.get("first_name") or "Không tên"
                    c_type = chat.get("type", "chat")
                    return cid, f"Đã tìm thấy {c_type.upper()}: '{title}' (Chat ID: {cid})"

            return None, "Không tìm thấy thông tin nhóm trong lịch sử cập nhật."
        except Exception as ex:
            return None, f"Lỗi phát hiện Chat ID: {ex}"

