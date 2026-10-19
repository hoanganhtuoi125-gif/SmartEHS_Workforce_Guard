import os
import sys
import warnings
import cv2
import numpy as np

# Bỏ qua các cảnh báo FutureWarning không cần thiết từ thư viện InsightFace
warnings.filterwarnings('ignore', category=FutureWarning)

# Nạp đường dẫn DLL của PyTorch CUDA (cublas64_12, cudnn64_9) vào Windows DLL search path cho ONNXRuntime
try:
    import torch
    torch_lib = os.path.join(os.path.dirname(torch.__file__), 'lib')
    if os.path.exists(torch_lib):
        if hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(torch_lib)
        os.environ['PATH'] = torch_lib + os.pathsep + os.environ.get('PATH', '')
except Exception:
    pass

import insightface
from insightface.app import FaceAnalysis

# Giới hạn số luồng CPU của OpenCV và OpenMP để tránh chiếm dụng 100% CPU
cv2.setNumThreads(2)
os.environ['OMP_NUM_THREADS'] = '2'
os.environ['MKL_NUM_THREADS'] = '2'
# Tắt warning vô ích của ONNXRuntime & InsightFace
os.environ['ORT_LOGGING_LEVEL'] = '3'

class InsightFaceEngine:
    def __init__(self, faces_dir="faces"):
        if not os.path.exists(faces_dir):
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
                internal_dir = getattr(sys, '_MEIPASS', os.path.join(base_dir, '_internal'))
                for cand in [os.path.join(base_dir, "faces"), os.path.join(internal_dir, "faces")]:
                    if os.path.exists(cand):
                        faces_dir = cand
                        break
        os.makedirs(faces_dir, exist_ok=True)
        self.faces_dir = faces_dir
        self.known_face_encodings = []
        self.known_face_names = []

        print("[-] Đang nạp InsightFace Engine...")
        
        # Thử khởi tạo với CUDA Provider
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        
        try:
            self.app = FaceAnalysis(name='buffalo_l', providers=providers)
            # Tối ưu kích thước det_size 320x320 giúp tăng tốc 300%
            self.app.prepare(ctx_id=0, det_size=(320, 320))
            
            # Kiểm tra Provider thực tế đang được nạp
            is_cuda = any('CUDAExecutionProvider' in getattr(m, 'session').get_providers() 
                          for m in self.app.models.values() if hasattr(m, 'session'))
            if is_cuda:
                print("[+] InsightFace chạy THỰC SỰ trên GPU CUDA (RTX 3050) thành công!")
            else:
                print("⚠️ InsightFace đang chạy trên CPU.")
        except Exception as e:
            print(f"⚠️ Không nạp được CUDA Execution Provider, chuyển sang CPU: {e}")
            self.app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
            self.app.prepare(ctx_id=-1, det_size=(320, 320))

        self.load_known_faces()

    def load_known_faces(self):
        self.known_face_encodings = []
        self.known_face_names = []
        if not os.path.exists(self.faces_dir):
            os.makedirs(self.faces_dir)

        for filename in os.listdir(self.faces_dir):
            if filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                name = os.path.splitext(filename)[0]
                img_path = os.path.join(self.faces_dir, filename)
                img = cv2.imread(img_path)
                if img is not None:
                    faces = self.app.get(img)
                    if len(faces) > 0:
                        self.known_face_encodings.append(faces[0].embedding)
                        self.known_face_names.append(name)
                        print(f"   [+] Đã nạp nhân sự: {name}")

    def recognize_faces(self, frame, threshold=0.5):
        results = []
        faces = self.app.get(frame)
        
        for face in faces:
            raw_bbox = getattr(face, 'bbox', None)
            if raw_bbox is None:
                continue
            bbox = raw_bbox.astype(int)
            embedding = getattr(face, 'embedding', None)
            if embedding is None:
                continue
            
            name = "Unknown"
            max_sim = 0.0
            
            if len(self.known_face_encodings) > 0:
                sims = [float(np.dot(embedding, k_emb) / (np.linalg.norm(embedding) * np.linalg.norm(k_emb))) 
                        for k_emb in self.known_face_encodings if k_emb is not None]
                best_idx = np.argmax(sims)
                if sims[best_idx] >= threshold:
                    name = self.known_face_names[best_idx]
                    max_sim = sims[best_idx]
            
            results.append({
                "name": name,
                "bbox": bbox,
                "similarity": float(max_sim)
            })
        return results