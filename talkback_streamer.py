import os
import sys
import threading
import time
import datetime
import wave
import socket
import urllib.parse
import urllib.request
import subprocess
import hashlib
import numpy as np
import sounddevice as sd
import urllib3
urllib3.disable_warnings()

# Đảm bảo mã hóa UTF-8 cho console Windows tránh UnicodeEncodeError khi in tiếng Việt
try:
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# Gỡ bỏ các biến môi trường CA bundle (như của PostgreSQL) làm sai lệch chứng chỉ camera nội bộ
os.environ.pop('CURL_CA_BUNDLE', None)
os.environ.pop('REQUESTS_CA_BUNDLE', None)
os.environ.pop('SSL_CERT_FILE', None)

import ssl
try:
    setattr(ssl, '_create_default_https_context', getattr(ssl, '_create_unverified_context', None))
except Exception:
    pass

import requests
from requests.adapters import HTTPAdapter

# Bỏ qua xác thực SSL cho Tapo camera cục bộ
_orig_cert_verify = getattr(HTTPAdapter, 'cert_verify', None)
def _insecure_cert_verify(self, conn, url, verify, cert):
    if _orig_cert_verify:
        return _orig_cert_verify(self, conn, url, False, cert)
    return None
if _orig_cert_verify:
    HTTPAdapter.cert_verify = _insecure_cert_verify

_orig_session_request = requests.Session.request
def _insecure_session_request(self, *args, **kwargs):
    kwargs['verify'] = False
    return _orig_session_request(self, *args, **kwargs)
requests.Session.request = _insecure_session_request

try:
    import pytapo
except ImportError:
    pytapo = None


class Go2RTCServiceManager:
    """
    Trình quản lý Engine go2rtc chạy ngầm phục vụ giao tiếp 2 chiều (Audio Backchannel)
    với Camera Tapo C200 / C210.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Go2RTCServiceManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, port=1984):
        if self._initialized:
            return
        self._initialized = True
        self.port = port
        self.process = None
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.exe_path = os.path.join(self.base_dir, "tools", "go2rtc.exe")
        self.yaml_path = os.path.join(self.base_dir, "go2rtc.yaml")
        self.current_tapo_ip = None

    def is_port_open(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4)
        try:
            res = s.connect_ex(('127.0.0.1', self.port))
            s.close()
            return res == 0
        except Exception:
            return False

    def update_config(self, tapo_ip, tapo_user="", tapo_pass="", tapo_cloud_pass=""):
        if not tapo_ip:
            return
        self.current_tapo_ip = tapo_ip
        p_cloud = (tapo_cloud_pass or "").strip()

        p_sha = hashlib.sha256(p_cloud.encode()).hexdigest().upper() if p_cloud else ""

        stream_lines = []
        if p_sha:
            stream_lines.append(f"    - \"tapo://admin:{p_sha}@{tapo_ip}\"")
        if tapo_user and tapo_pass:
            stream_lines.append(f"    - \"rtsp://{tapo_user}:{tapo_pass}@{tapo_ip}:554/stream1\"")

        streams_block = (
            "streams:\n"
            "  tapo_cam:\n" + ("\n".join(stream_lines) + "\n" if stream_lines else "    []\n") +
            "  tapo_talk:\n" + (f"    - \"tapo://admin:{p_sha}@{tapo_ip}\"\n" if p_sha else "    []\n")
        )

        content = (
            "log:\n"
            "  level: info\n\n"
            "api:\n"
            f"  listen: \"127.0.0.1:{self.port}\"\n\n"
            "rtsp:\n"
            "  listen: \"127.0.0.1:8554\"\n\n"
            f"{streams_block}"
        )
        try:
            with open(self.yaml_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            print(f"[Go2RTC] Lỗi ghi go2rtc.yaml: {e}")

        tools_dir = os.path.join(self.base_dir, "tools")
        if tools_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = tools_dir + os.pathsep + os.environ.get("PATH", "")

    def start_if_needed(self, tapo_ip, tapo_user="", tapo_pass="", tapo_cloud_pass=""):
        config_changed = (
            getattr(self, "current_tapo_ip", None) != tapo_ip or
            getattr(self, "current_cloud_pass", None) != tapo_cloud_pass
        )
        self.current_cloud_pass = tapo_cloud_pass
        self.update_config(tapo_ip, tapo_user, tapo_pass, tapo_cloud_pass)

        if config_changed and self.is_port_open():
            self.stop()
            time.sleep(0.3)

        if self.is_port_open():
            return True

        if not os.path.exists(self.exe_path):
            print(f"[Go2RTC] Không tìm thấy file {self.exe_path}")
            return False

        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # Ẩn cửa sổ dòng lệnh hoàn toàn

            self.process = subprocess.Popen(
                [self.exe_path, "-c", self.yaml_path],
                cwd=self.base_dir,
                startupinfo=si,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            # Chờ service khởi động
            for _ in range(12):
                time.sleep(0.15)
                if self.is_port_open():
                    print("[Go2RTC] [+] Engine truyền âm thanh đàm thoại 2 chiều đã kích hoạt.")
                    return True
            return False
        except Exception as e:
            print(f"[Go2RTC] Không thể khởi chạy engine: {e}")
            return False

    def stop(self):
        """ Dừng tiến trình go2rtc ngầm khi đóng ứng dụng """
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=1.5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def push_audio_file(self, wav_path):
        """ Đẩy tệp âm thanh trực tiếp tới Loa Camera Tapo qua kênh âm thanh ngược WebRTC (Backchannel) """
        if not self.is_port_open():
            return False, "Engine go2rtc chưa sẵn sàng."

        if not os.path.exists(wav_path):
            return False, "Tệp âm thanh không tồn tại."

        try:
            import asyncio
            import urllib.request
            import urllib.error
            import concurrent.futures
            from aiortc import RTCPeerConnection, RTCSessionDescription, AudioStreamTrack
            from av import AudioFrame

            with wave.open(wav_path, 'rb') as wf:
                rate = wf.getframerate()
                channels = wf.getnchannels()
                raw = wf.readframes(wf.getnframes())
                if channels == 1:
                    audio_data = np.frombuffer(raw, dtype=np.int16)
                else:
                    interleaved = np.frombuffer(raw, dtype=np.int16)
                    audio_data = interleaved[::channels]

            total_samples = len(audio_data)
            duration = total_samples / float(rate)
            chunk_size = int(rate * 0.02)

            class FileAudioTrack(AudioStreamTrack):
                def __init__(self):
                    super().__init__()
                    self.idx = 0
                    self.pts = 0

                async def recv(self):
                    pts = self.pts
                    self.pts += chunk_size
                    if self.idx + chunk_size <= total_samples:
                        chunk = audio_data[self.idx:self.idx + chunk_size]
                        self.idx += chunk_size
                    else:
                        rem = total_samples - self.idx
                        if rem > 0:
                            chunk = np.pad(audio_data[self.idx:], (0, chunk_size - rem), mode='constant')
                            self.idx = total_samples
                        else:
                            chunk = np.zeros(chunk_size, dtype=np.int16)

                    frame = AudioFrame(format='s16', layout='mono', samples=chunk_size)
                    frame.pts = pts
                    frame.sample_rate = rate
                    for plane in frame.planes:
                        plane.update(chunk.tobytes())
                    return frame

            async def _push():
                pc = RTCPeerConnection()
                # Thêm transceiver video recvonly và audio sendrecv để đồng bộ định dạng media Tapo
                pc.addTransceiver('video', direction='recvonly')
                pc.addTransceiver('audio', direction='sendrecv')
                track = FileAudioTrack()
                pc.addTrack(track)

                offer = await pc.createOffer()
                await pc.setLocalDescription(offer)

                # Chờ hoàn thành ICE gathering
                while pc.iceGatheringState != 'complete':
                    await asyncio.sleep(0.05)

                streams_to_try = [
                    f"http://127.0.0.1:{self.port}/api/webrtc?src=tapo_talk&media=video+audio+microphone",
                    f"http://127.0.0.1:{self.port}/api/webrtc?src=tapo_cam&media=video+audio+microphone"
                ]
                answer_sdp = None
                last_err = ""
                loop = asyncio.get_running_loop()

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    for api_url in streams_to_try:
                        req = urllib.request.Request(
                            api_url,
                            data=pc.localDescription.sdp.encode('utf-8'),
                            headers={'Content-Type': 'application/sdp'},
                            method='POST'
                        )
                        def _fetch(r=req):
                            with urllib.request.urlopen(r, timeout=6.0) as resp:
                                return resp.status, resp.read().decode('utf-8')

                        try:
                            st, body = await loop.run_in_executor(pool, _fetch)
                            if st in (200, 201) and body:
                                answer_sdp = body
                                break
                            else:
                                last_err = f"HTTP {st}"
                        except urllib.error.HTTPError as he:
                            last_err = f"HTTP Error {he.code}: {he.reason}"
                            if he.code in (401, 500):
                                break
                        except Exception as ex:
                            last_err = str(ex)

                if not answer_sdp:
                    await pc.close()
                    return False, last_err or "Không nhận được phản hồi WebRTC từ Camera Tapo."

                await pc.setRemoteDescription(RTCSessionDescription(answer_sdp, 'answer'))
                await asyncio.sleep(duration + 0.5)
                await pc.close()
                return True, f"Đã phát âm thanh ({duration:.1f}s) thành công ra Loa Camera Tapo."

            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_push())
            finally:
                loop.close()

        except Exception as e:
            return False, f"Lỗi phát WebRTC: {e}"


class TalkbackStreamer:
    """
    Module Đàm thoại / Giao tiếp âm thanh 2 chiều với Camera Tapo:
    1. Thu âm qua Micro Laptop của người giám sát:
       - Hỗ trợ 'Giữ để nói' (Push to Talk) và 'Nói trực tiếp' (Toggle Live Mic).
       - TUYỆT ĐỐI KHÔNG phát lặp lại ra loa laptop.
       - Đo cường độ âm thanh (RMS Level) để hiển thị sóng âm VU meter trên giao diện.
    2. Truyền phát âm thanh giọng nói tới Camera Tapo C200 / Loa hiện trường:
       - Tự động đồng bộ âm lượng cấu hình qua giao thức Tapo.
       - Truyền luồng giọng nói trực tiếp tới Loa Camera Tapo qua Audio Backchannel.
       - Tự động ngắt loa camera ngay khi hết thời lượng.
    3. Hỗ trợ phát lại thông báo gần nhất và kiểm tra loa camera.
    """
    def __init__(self):
        self.is_recording = False
        self.is_broadcasting = False
        self.is_talking = False
        self.is_live_talking = False
        self.stream = None
        self.current_cam = None
        self.lock = threading.Lock()
        self.on_volume_callback = None
        self.on_status_callback = None
        self.last_volume = 0.0
        self.sample_rate = 16000
        self.recorded_frames = []
        self.record_start_time = 0.0
        self.last_audio_file = os.path.abspath("temp_voice/thong_bao_tam.wav")
        self.tapo_cam_client = None
        self.tapo_volume = 80

        os.makedirs("temp_voice", exist_ok=True)
        self.go2rtc_mgr = Go2RTCServiceManager()

    def _ensure_engine(self, cam_info):
        """ Khởi động và chuẩn bị engine đàm thoại cho camera đã chọn """
        cam = cam_info or self.current_cam or {}
        ip = cam.get("tapo_ip")
        if not ip and "@" in str(cam.get("source", "")):
            try:
                ip = str(cam.get("source", "")).split("@")[1].split(":")[0]
            except Exception:
                pass
        if ip:
            user = cam.get("tapo_user", "")
            pwd = cam.get("tapo_pass", "")
            cloud = cam.get("tapo_cloud_pass", "")
            self.go2rtc_mgr.start_if_needed(ip, user, pwd, cloud)

    def set_tapo_volume(self, cam_info, volume: int):
        """ Thiết lập cường độ âm lượng Loa Tapo (10% - 100%) """
        vol = max(10, min(100, volume))
        self.tapo_volume = vol

        def _apply_vol():
            client, _ = self._get_tapo_client(cam_info)
            if client:
                try:
                    client.setSpeakerVolume(vol)
                    print(f"[Talkback] [+] Đã đặt âm lượng loa Camera Tapo: {vol}%")
                except Exception as e:
                    print(f"[Talkback] Không thể đặt âm lượng Tapo: {e}")
        threading.Thread(target=_apply_vol, daemon=True).start()
        return vol

    def start_hold_to_talk(self, cam_info, volume=None, on_volume_cb=None, on_status_cb=None):
        """
        CHỨC NĂNG 'GIỮ ĐỂ NÓI CHUYỆN' (GIỐNG APP TAPO TRÊN ĐIỆN THOẠI):
        - Nhấn giữ chuột: Bắt đầu thu âm giọng nói của người giám sát từ Micro.
        - Hiển thị sóng âm VU meter nhảy theo giọng nói.
        """
        return self.start_live_talk(cam_info, volume=volume, on_volume_cb=on_volume_cb, on_status_cb=on_status_cb, mode="hold")

    def stop_hold_to_talk(self, on_finish_cb=None):
        """
        THẢ CHUỘT RA:
        - Tự động kết thúc thu âm và truyền phát ngay lập tức giọng nói tới Loa Camera Tapo.
        """
        return self.stop_live_talk(on_finish_cb=on_finish_cb)

    def start_live_talk(self, cam_info, volume=None, on_volume_cb=None, on_status_cb=None, mode="toggle"):
        """
        ĐÀM THOẠI TRỰC TIẾP (LIVE MIC PASS-THROUGH / HOLD-TO-TALK):
        - Thu âm trực tiếp qua Micro laptop người giám sát.
        - Đo cường độ giọng nói (VU meter) thời gian thực.
        """
        with self.lock:
            if self.is_talking:
                return False
            self.is_talking = True
            self.is_live_talking = True
            self.is_recording = True
            self.current_cam = cam_info or {}
            self.on_volume_callback = on_volume_cb
            self.on_status_callback = on_status_cb
            self.recorded_frames = []
            self.record_start_time = time.time()

        if volume is not None:
            self.set_tapo_volume(cam_info, volume)

        cam_name = cam_info.get("name", "Camera") if cam_info else "Camera"
        cam_type = cam_info.get("type", "") if cam_info else ""
        is_tapo = (cam_type == "tapo" or "tapo" in str(cam_name).lower())

        # Khởi động dịch vụ stream ngầm tới camera
        threading.Thread(target=self._ensure_engine, args=(cam_info,), daemon=True).start()

        def mic_live_callback(indata, frames, time_info, status):
            if not self.is_talking:
                return
            try:
                # 1. Đo mức âm lượng thời gian thực cho VU progress bar
                rms = np.sqrt(np.mean(indata**2))
                vol = min(1.0, float(rms * 14.0))
                self.last_volume = vol
                if self.on_volume_callback:
                    self.on_volume_callback(vol)

                # 2. Ghi bộ đệm âm thanh
                self.recorded_frames.append(indata.copy())
            except Exception:
                pass

        try:
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                blocksize=1024,
                channels=1,
                dtype='float32',
                callback=mic_live_callback
            )
            self.stream.start()

            dest_str = "CAMERA TAPO" if is_tapo else cam_name[:20]
            action_desc = "GIỮ CHUỘT ĐỂ NÓI..." if mode == "hold" else "ĐANG NÓI TRỰC TIẾP..."
            if self.on_status_callback:
                self.on_status_callback(f"🔴 {action_desc} (-> {dest_str.upper()})")
            print(f"[Talkback] [+] Đã kích hoạt Micro thu âm (-> {dest_str}).")
            return True

        except Exception as e:
            print(f"[Talkback] Lỗi khởi động Micro: {e}")
            self.is_talking = False
            self.is_live_talking = False
            self.is_recording = False
            if self.on_status_callback:
                self.on_status_callback(f"⚠️ Lỗi kết nối Micro: {e}")
            return False

    def stop_live_talk(self, on_finish_cb=None):
        """
        DỪNG NÓI:
        - Tắt luồng Micro laptop.
        - Lưu file WAV và lập tức truyền phát sang Loa Camera Tapo.
        """
        with self.lock:
            if not self.is_talking:
                return
            self.is_talking = False
            self.is_live_talking = False
            self.is_recording = False

        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        if self.on_volume_callback:
            try:
                self.on_volume_callback(0.0)
            except Exception:
                pass

        # Lưu file WAV và truyền phát ra Loa Camera Tapo
        if self.recorded_frames:
            try:
                all_data = np.concatenate(self.recorded_frames, axis=0)
                int16_data = (all_data * 32767.0).clip(-32768, 32767).astype(np.int16)
                wav_path = os.path.abspath("temp_voice/thong_bao_tam.wav")
                with wave.open(wav_path, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(self.sample_rate)
                    wf.writeframes(int16_data.tobytes())
                self.last_audio_file = wav_path

                # Tự động truyền phát giọng nói vừa thu ra Loa Camera Tapo
                cam = self.current_cam
                def _auto_broadcast():
                    time.sleep(0.05)
                    self.broadcast_last_audio(cam, on_finish_cb=on_finish_cb)
                threading.Thread(target=_auto_broadcast, daemon=True).start()
                return
            except Exception as e:
                print(f"[Talkback] Lỗi xử lý âm thanh: {e}")

        if self.on_status_callback:
            self.on_status_callback("✅ Đã kết thúc đàm thoại.")

        if on_finish_cb:
            try:
                on_finish_cb()
            except Exception:
                pass

    def broadcast_last_audio(self, cam_info=None, on_finish_cb=None):
        """
        Truyền phát tệp âm thanh vừa thu hoặc tệp thông báo ra Loa Camera Tapo
        (TUYỆT ĐỐI KHÔNG PHÁT RA LOA LAPTOP BẰNG WINSOUND NỮA)
        """
        if self.is_recording or self.is_broadcasting:
            return False

        wav_path = self.last_audio_file
        if not wav_path or not os.path.exists(wav_path):
            if self.on_status_callback:
                self.on_status_callback("⚠️ Chưa có đoạn âm thanh đàm thoại nào.")
            return False

        try:
            with wave.open(wav_path, 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                duration = frames / float(rate)
        except Exception:
            duration = 3.0

        if duration < 0.2:
            return False

        cam = cam_info or self.current_cam
        threading.Thread(target=self._broadcast_worker, args=(cam, wav_path, duration, on_finish_cb), daemon=True).start()
        return True

    def _broadcast_worker(self, cam_info, wav_path, duration, on_finish_cb=None):
        """ Luồng thực thi truyền phát âm thanh tới Loa Camera Tapo """
        with self.lock:
            self.is_broadcasting = True

        try:
            cam_name = cam_info.get("name", "Camera") if cam_info else "Camera"
            cam_type = cam_info.get("type", "") if cam_info else ""
            is_tapo = (cam_type == "tapo" or "tapo" in str(cam_name).lower())

            dest_str = "CAMERA TAPO" if is_tapo else cam_name[:20]
            if self.on_status_callback:
                self.on_status_callback(f"📢 ĐANG TRUYỀN ÂM THANH SANG {dest_str.upper()} ({duration:.1f}s)...")

            # Đảm bảo engine chạy và cấu hình đúng
            self._ensure_engine(cam_info)

            # Đặt âm lượng loa Camera Tapo trước khi phát
            client, _ = self._get_tapo_client(cam_info)
            if client:
                try:
                    client.setSpeakerVolume(self.tapo_volume)
                except Exception:
                    pass

            # 1. ĐẨY ÂM THANH TRỰC TIẾP TỚI LOA CAMERA QUA GO2RTC BACKCHANNEL
            pushed, push_msg = self.go2rtc_mgr.push_audio_file(wav_path)
            if pushed:
                print(f"[Talkback] [+] Đã truyền âm thanh tới Loa Camera Tapo ({push_msg})")
                if self.on_status_callback:
                    self.on_status_callback(f"📢 Loa Tapo đang phát giọng nói ({duration:.1f}s)...")
                # Chờ hết thời lượng âm thanh
                wait_time = max(duration, 0.8)
                time.sleep(wait_time)
                if self.on_status_callback:
                    self.on_status_callback(f"✅ Đã phát giọng nói ra Loa Camera Tapo ({duration:.1f}s)!")
            else:
                print(f"[Talkback] [!] go2rtc push thất bại: {push_msg}")
                if "401" in push_msg or "500" in push_msg or "Unauthorized" in push_msg:
                    diag_msg = (
                        "⚠️ Loa Tapo từ chối (401): Mở App Tapo -> Tôi -> Tapo Lab "
                        "-> Bật 'Hỗ trợ bên thứ ba' & khởi động lại camera"
                    )
                else:
                    diag_msg = f"⚠️ Chưa thể truyền âm thanh: {push_msg}"
                if self.on_status_callback:
                    self.on_status_callback(diag_msg)

        finally:
            with self.lock:
                self.is_broadcasting = False

            if on_finish_cb:
                try:
                    on_finish_cb()
                except Exception:
                    pass

    def test_tapo_speaker(self, cam_info, volume=None):
        """
        Kiểm tra và thử Loa Camera Tapo.
        Trả về (thành_công: bool, thông_báo: str)
        """
        if volume is not None:
            self.tapo_volume = max(10, min(100, int(volume)))

        client, err = self._get_tapo_client(cam_info)
        if not client:
            return False, f"Không thể kết nối tới Camera Tapo:\n{err}"

        try:
            client.setSpeakerVolume(self.tapo_volume)
        except Exception:
            pass

        # Thử kích hoạt chuông kiểm tra loa camera Tapo trong 1.5 giây
        try:
            client.testUsrDefAudio(1, True)
            time.sleep(1.5)
            client.testUsrDefAudio(1, False)
            return True, (
                f"✅ Loa Camera Tapo C200 đã phản hồi âm thanh thành công ở mức âm lượng {self.tapo_volume}%!\n\n"
                "💡 ĐỂ ĐÀM THOẠI 2 CHIỀU TRUYỀN GIỌNG NÓI TỪ MÁY CHỦ:\n"
                "Nếu máy chủ chưa truyền được tiếng nói sang camera, bạn chỉ cần mở App Tapo trên điện thoại:\n"
                "👉 Vào 'Tôi (Me)' -> 'Tapo Lab' -> Bật 'Third-Party Compatibility' (Hỗ trợ bên thứ ba) là xong!"
            )
        except Exception as e:
            return False, f"Camera đã xác thực nhưng loa chưa phản hồi: {e}"

    def _get_tapo_client(self, cam_info):
        """ Tạo hoặc tái sử dụng client kết nối Tapo camera """
        if not pytapo:
            return None, "Thư viện pytapo chưa được cài đặt."

        cam_info = cam_info or {}
        ip = cam_info.get("tapo_ip")
        if not ip:
            src = str(cam_info.get("source", ""))
            if "@" in src and ":" in src:
                try:
                    ip = src.split("@")[1].split(":")[0]
                except Exception:
                    pass

        if not ip:
            try:
                import json
                possible_paths = ["settings.json", os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")]
                for pth in possible_paths:
                    if os.path.exists(pth):
                        with open(pth, "r", encoding="utf-8") as f:
                            st = json.load(f)
                            for c in st.get("cameras", []):
                                if c.get("type") == "tapo" or "tapo" in str(c.get("name", "")).lower():
                                    ip = c.get("tapo_ip")
                                    if ip:
                                        for k, v in c.items():
                                            if k not in cam_info:
                                                cam_info[k] = v
                                        break
                            if ip:
                                break
            except Exception:
                pass

        if not ip:
            return None, "Không tìm thấy địa chỉ IP của Camera Tapo."

        cloud_password = cam_info.get("tapo_cloud_pass", "").strip()
        user = cam_info.get("tapo_user", "")
        password = cam_info.get("tapo_pass", "")

        candidates = []
        if cloud_password:
            candidates.append(cloud_password)
        if password and password not in candidates:
            candidates.append(password)

        last_error = None
        for p in candidates:
            try:
                client = pytapo.Tapo(ip, "admin", p, cloudPassword=p, printDebugInformation=False)
                return client, None
            except Exception as e:
                last_error = str(e)
            try:
                if user:
                    client = pytapo.Tapo(ip, user, p, cloudPassword=p, printDebugInformation=False)
                    return client, None
            except Exception as e:
                last_error = str(e)

        return None, last_error or "Không thể xác thực với Camera Tapo."

    def stop_recording(self, save_wav=True):
        return self.stop_live_talk(on_finish_cb=None)

    def close(self):
        """ Dọn dẹp tài nguyên khi thoát ứng dụng """
        self.stop_live_talk()
        self.is_broadcasting = False
        if hasattr(self, 'go2rtc_mgr') and self.go2rtc_mgr:
            try:
                self.go2rtc_mgr.stop()
            except Exception:
                pass

    # --- CÁC HÀM TƯƠNG THÍCH VỚI CODE CŨ ---
    def start_talk(self, cam_info, on_volume_cb=None, on_status_cb=None):
        return self.start_live_talk(cam_info, on_volume_cb=on_volume_cb, on_status_cb=on_status_cb)

    def stop_talk(self, on_finish_cb=None):
        return self.stop_live_talk(on_finish_cb=on_finish_cb)
