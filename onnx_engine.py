import torch
from ultralytics import YOLO

class PyTorchGPUEngine:
    def __init__(self, model_path):
        print(f"[-] Đang nạp mô hình PyTorch lên GPU RTX 3050: {model_path}")
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
        # Nạp mô hình PyTorch và chuyển sang GPU CUDA
        self.model = YOLO(model_path)
        self.model.to(self.device)
        
        print(f"[+] Đã kích hoạt thiết bị: {self.device.upper()} ({torch.cuda.get_device_name(0)})")

    def infer(self, frame):
        # Chạy suy luận với chế độ FP16 trên CUDA
        kwargs = {
            "source": frame,
            "verbose": False,
            "device": self.device
        }
        if self.device == 'cuda':
            kwargs["quantize"] = "fp16"
        results = self.model.predict(**kwargs)
        return results