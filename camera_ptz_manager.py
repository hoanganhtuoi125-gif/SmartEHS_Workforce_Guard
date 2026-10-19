import cv2
import time
import threading
import os
from onvif import ONVIFCamera

# Ép OpenCV xả đệm RTSP UDP siêu nhẹ
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "fflags;nobuffer|flags;low_delay|rtsp_transport;udp"

CAM_IP = ""
CAM_USER = ""
CAM_PASS = ""
RTSP_URL = f"rtsp://{CAM_USER}:{CAM_PASS}@{CAM_IP}:554/stream1" if len(CAM_IP) > 0 else ""

class ZeroDelayRTSPEngine:
    def __init__(self, rtsp_url):
        self.rtsp_url = rtsp_url
        self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.frame = None
        self.ret = False
        self.is_running = False
        self.lock = threading.Lock()

    def start(self):
        if self.is_running:
            return self
        self.is_running = True
        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()
        print(" [+] Đã kích hoạt luồng camera RTSP.")
        return self

    def _update_loop(self):
        while self.is_running:
            if not self.cap.isOpened():
                time.sleep(0.2)
                continue
            ret, frame = self.cap.read()
            if ret and frame is not None:
                with self.lock:
                    self.frame = frame
                    self.ret = ret
            else:
                time.sleep(0.01)

    def retrieve_frame(self):
        with self.lock:
            if self.ret and self.frame is not None:
                return True, self.frame.copy()
            return False, None

    def stop(self):
        self.is_running = False
        self.cap.release()

if __name__ == "__main__":
    print("[-] Đang mở camera...")
    rtsp_engine = ZeroDelayRTSPEngine(RTSP_URL).start()
    
    # Chờ 1 giây cho luồng camera ổn định
    time.sleep(1.0)

    while True:
        ret, frame = rtsp_engine.retrieve_frame()
        if ret and frame is not None:
            display_frame = cv2.resize(frame, (960, 540))
            cv2.imshow("TAPO C200 LIVE", display_frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    rtsp_engine.stop()
    cv2.destroyAllWindows()