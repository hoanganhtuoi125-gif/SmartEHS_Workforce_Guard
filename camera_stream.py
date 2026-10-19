import cv2
import threading
import time

class RTSPCameraStream:
    def __init__(self, rtsp_url):
        self.rtsp_url = rtsp_url
        self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        self.grabbed, self.frame = self.cap.read()
        self.started = False
        self.read_lock = threading.Lock()

    def start(self):
        if self.started:
            return None
        self.started = True
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True
        self.thread.start()
        return self

    def update(self):
        """ Vòng lặp cap.grab() liên tục để triệt tiêu trễ bộ đệm RTSP (Buffer Bloat) """
        while self.started:
            # Liên tục xả bộ đệm phần cứng bằng cap.grab()
            grabbed = self.cap.grab()
            if not grabbed:
                time.sleep(0.01)
                continue

    def read_latest_frame(self):
        """ Chỉ giải mã điểm ảnh cap.retrieve() khi AI Engine báo Ready Flag """
        ret, frame = self.cap.retrieve()
        return ret, frame

    def stop(self):
        self.started = False
        if self.thread.is_alive():
            self.thread.join()
        self.cap.release()


class CameraLiveAudioReceiver:
    """ Luồng thu và phát âm thanh trực tiếp từ Camera (RTSP mic) ra loa máy tính khi người dùng phóng to camera """
    def __init__(self):
        self.is_running = False
        self.thread = None
        self.current_source = None
        self.lock = threading.Lock()

    def start_listening(self, source_url):
        self.stop_listening()
        if not source_url or str(source_url).strip().isdigit():
            # Webcam USB không có RTSP stream
            return False

        with self.lock:
            self.is_running = True
            self.current_source = str(source_url).strip()
            self.thread = threading.Thread(target=self._audio_loop, daemon=True)
            self.thread.start()
        return True

    def _audio_loop(self):
        try:
            import av
            import sounddevice as sd
        except ImportError:
            return

        src = self.current_source
        container = None
        try:
            container = av.open(src, options={'rtsp_transport': 'udp', 'stimeout': '2000000'})
            audio_stream = next((s for s in container.streams if s.type == 'audio'), None)
            if not audio_stream:
                return

            from typing import Any
            in_container: Any = container
            rate = getattr(audio_stream, 'rate', None) or getattr(audio_stream, 'sample_rate', 8000) or 8000
            channels = getattr(audio_stream, 'channels', None) or 1

            with sd.RawOutputStream(samplerate=rate, channels=channels, dtype='int16') as out_stream:
                for packet in in_container.demux(audio_stream):
                    if not self.is_running:
                        break
                    for frame in packet.decode():
                        if not self.is_running:
                            break
                        raw_bytes = frame.to_ndarray().tobytes()
                        out_stream.write(raw_bytes)
        except Exception as e:
            print(f"[CameraAudio] Lỗi luồng nghe âm thanh camera: {e}")
        finally:
            if container:
                try:
                    container.close()
                except Exception:
                    pass

    def stop_listening(self):
        with self.lock:
            self.is_running = False
        self.thread = None