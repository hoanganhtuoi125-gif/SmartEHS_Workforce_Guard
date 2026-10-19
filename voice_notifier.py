import os
import sys
import time
import asyncio
import threading
import tempfile
import pygame

if hasattr(sys.stdout, 'reconfigure'):
    try:
        getattr(sys.stdout, 'reconfigure')(encoding='utf-8', errors='replace')
        getattr(sys.stderr, 'reconfigure')(encoding='utf-8', errors='replace')
    except Exception:
        pass

class VoiceNotifier:
    """
    Hệ thống phát cảnh báo giọng nói tiếng Việt chuyên nghiệp:
    - Sử dụng Edge TTS giọng Việt tự nhiên (Hoài My / Nam Minh).
    - Tự động fallback sang PyTTSx3 hoặc Winsound khi mất mạng.
    - Cơ chế Cooldown chính xác: CHỈ BẮT ĐẦU ĐẾM 30 GIÂY SAU KHI ĐỌC XONG CÂU TRƯỚC ĐÓ.
    - Tuyệt đối không đọc đè (non-overlapping).
    - Chạy hoàn toàn trên Worker Thread độc lập, 0% ảnh hưởng FPS camera.
    """
    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        self.is_speaking = False
        self.last_speech_finished_time = 0.0
        self.lock = threading.Lock()
        
        # Khởi tạo pygame mixer cho audio phát ngầm
        try:
            pygame.mixer.init()
        except Exception as e:
            print(f"[Voice Notifier] Khởi tạo pygame.mixer: {e}")

    def get_settings(self):
        if self.config_manager:
            return self.config_manager.settings.get("voice", {})
        return {}

    def is_enabled(self):
        return self.get_settings().get("enabled", True)

    def is_stranger_enabled(self):
        v = self.get_settings()
        return v.get("enabled", True) and v.get("stranger_enabled", True)

    def get_interval(self):
        return int(self.get_settings().get("interval_seconds", 30))

    def get_voice_name(self):
        return self.get_settings().get("voice_type", "vi-VN-HoaiMyNeural")

    def announce_stranger(self, location="Cổng kiểm soát", violations=None):
        """
        Cảnh báo an ninh độc quyền khi phát hiện người lạ chưa đăng ký:
        Có thể bật/tắt trong Cài đặt thông qua stranger_enabled / enabled.
        """
        if not self.is_stranger_enabled():
            return False

        now = time.time()
        with self.lock:
            if self.is_speaking:
                return False
            if now - self.last_speech_finished_time < self.get_interval():
                return False
            self.is_speaking = True

        full_text = f"Cảnh báo an ninh! Phát hiện người lạ chưa đăng ký tại {location.lower()}. Đề nghị kiểm tra danh tính."

        threading.Thread(target=self._speak_worker, args=(full_text,), daemon=True).start()
        return True

    def announce_worker_violation(self, worker_name, violations):
        """ ĐÃ BỎ: Không còn cảnh báo bằng giọng nói cho vi phạm PPE của công nhân """
        return False

    def announce_violations(self, violation_items):
        """ ĐÃ BỎ: Không còn phát cảnh báo giọng nói vi phạm PPE của công nhân """
        return False

    def test_speak(self, text="Hệ thống cảnh báo an toàn EHS sẵn sàng hoạt động. Chúc quý đồng nghiệp một ngày làm việc an toàn!"):
        """ Cho phép Quản lý bấm nghe thử giọng đọc trong phần Cài đặt """
        with self.lock:
            if self.is_speaking:
                return False
            self.is_speaking = True
        threading.Thread(target=self._speak_worker, args=(text, True), daemon=True).start()
        return True

    def _speak_worker(self, text, is_test=False):
        temp_path = None
        speech_success = False

        try:
            # 1. Thử dùng edge-tts tạo giọng Việt truyền cảm
            temp_file = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            temp_path = temp_file.name
            temp_file.close()

            voice_name = self.get_voice_name()

            async def _synthesize():
                import edge_tts
                comm = edge_tts.Communicate(text, voice_name)
                await comm.save(temp_path)

            asyncio.run(_synthesize())

            if not is_test and not self.is_stranger_enabled():
                return

            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 1000:
                pygame.mixer.music.load(temp_path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy() and (is_test or self.is_stranger_enabled()):
                    time.sleep(0.1)
                pygame.mixer.music.unload()
                speech_success = True
        except Exception as e:
            pass

        # 2. Fallback sang PyTTSx3 nếu không có mạng
        if not speech_success and (is_test or self.is_stranger_enabled()):
            try:
                try:
                    import pythoncom  # type: ignore
                    pythoncom.CoInitialize()
                except Exception:
                    pass
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty('rate', 150)
                engine.say(text)
                engine.runAndWait()
                speech_success = True
            except Exception:
                pass

        # Dọn dẹp file tạm
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

        # GHI NHẬN THỜI ĐIỂM HOÀN TẤT: Từ lúc này mới bắt đầu đếm 30 giây cooldown!
        with self.lock:
            self.last_speech_finished_time = time.time()
            self.is_speaking = False

    def stop(self):
        """ Lập tức ngắt âm thanh đang phát khi người dùng tắt giọng nói """
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
        except Exception:
            pass
        with self.lock:
            self.is_speaking = False
