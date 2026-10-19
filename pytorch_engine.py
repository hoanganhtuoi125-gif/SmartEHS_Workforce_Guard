import os
import sys
import torch
from ultralytics import YOLO
import cv2

class PyTorchGPUEngine:
    def __init__(self, model_path="best.pt"):
        # Tìm đường dẫn thực tế của model (hỗ trợ cả chạy script và chạy .exe PyInstaller)
        resolved_path = model_path
        if not os.path.exists(resolved_path):
            candidates = [
                os.path.join("models", "best.pt"),
                "best.pt",
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "best.pt"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "best.pt"),
            ]
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
                internal_dir = getattr(sys, '_MEIPASS', os.path.join(base_dir, '_internal'))
                candidates.extend([
                    os.path.join(base_dir, "models", "best.pt"),
                    os.path.join(base_dir, "best.pt"),
                    os.path.join(internal_dir, "models", "best.pt"),
                    os.path.join(internal_dir, "best.pt"),
                ])
            for c in candidates:
                if os.path.exists(c):
                    resolved_path = c
                    break

        print(f"[-] Đang nạp mô hình PyTorch lên GPU RTX 3050: {resolved_path}")
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.model = YOLO(resolved_path)
        
        if self.device == 'cuda':
            print(f"[+] Đã kích hoạt GPU CUDA FP16: {torch.cuda.get_device_name(0)}")
        else:
            print("⚠️ CẢNH BÁO: Đang chạy trên CPU! Hãy kiểm tra lại CUDA PyTorch.")

    def infer(self, frame, conf=0.45):
        """ Suy luận AI siêu tốc độ trên GPU CUDA """
        # Chạy inference trực tiếp với imgsz=640 để đạt FPS tối đa
        predict_kwargs = {
            "source": frame,
            "device": self.device,
            "conf": conf,
            "imgsz": 640,
            "verbose": False
        }
        if self.device == 'cuda':
            predict_kwargs["quantize"] = "fp16"
        results = self.model.predict(**predict_kwargs)
        return results