import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import os
from typing import Any

# Nạp font tiếng Việt Arial chuẩn Windows
try:
    FONT_PATH = "arial.ttf"
    _test_font = ImageFont.truetype(FONT_PATH, 14)
except Exception:
    FONT_PATH = "segoeui.ttf"

_font_cache: dict[int, Any] = {}

def get_font(size: int) -> Any:
    if size not in _font_cache:
        try:
            _font_cache[size] = ImageFont.truetype(FONT_PATH, size)
        except Exception:
            _font_cache[size] = ImageFont.load_default()
    return _font_cache[size]

VI_PPE_NAMES = {
    'helmet': ('MŨ BẢO HỘ', False),
    'no helmet': ('CHƯA ĐỘI MŨ', True),
    'no-helmet': ('CHƯA ĐỘI MŨ', True),
    'no_helmet': ('CHƯA ĐỘI MŨ', True),
    'vest': ('ÁO PHẢN QUANG', False),
    'no vest': ('CHƯA MẶC ÁO', True),
    'no-vest': ('CHƯA MẶC ÁO', True),
    'no_vest': ('CHƯA MẶC ÁO', True),
    'gloves': ('GĂNG TAY', False),
    'no gloves': ('CHƯA ĐEO GĂNG', True),
    'no-gloves': ('CHƯA ĐEO GĂNG', True),
    'glasses': ('KÍNH AN TOÀN', False),
    'no glasses': ('CHƯA ĐEO KÍNH', True),
    'no-glasses': ('CHƯA ĐEO KÍNH', True),
    'boots': ('GIÀY BẢO HỘ', False),
    'no boots': ('CHƯA MANG GIÀY', True),
    'no-boots': ('CHƯA MANG GIÀY', True),
}

def draw_tech_corners(img, box, color=(0, 255, 0), thickness=2, length=14):
    """ Vẽ khung góc công nghệ cao thay vì vẽ hộp thô chữ nhật """
    x1, y1, x2, y2 = [int(v) for v in box]
    w = x2 - x1
    h = y2 - y1
    L = max(length, min(w // 3, h // 3, 20))

    # Viền mờ bao quanh
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)

    # 4 góc dày nổi bật
    # Top-Left
    cv2.line(img, (x1, y1), (x1 + L, y1), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x1, y1), (x1, y1 + L), color, thickness, cv2.LINE_AA)
    # Top-Right
    cv2.line(img, (x2, y1), (x2 - L, y1), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x2, y1), (x2, y1 + L), color, thickness, cv2.LINE_AA)
    # Bottom-Left
    cv2.line(img, (x1, y2), (x1 + L, y2), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x1, y2), (x1, y2 - L), color, thickness, cv2.LINE_AA)
    # Bottom-Right
    cv2.line(img, (x2, y2), (x2 - L, y2), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x2, y2), (x2, y2 - L), color, thickness, cv2.LINE_AA)

def render_camera_overlay(frame_bgr, ppe_objects, face_results, ppe_enabled, bgr_pass=(0, 255, 0), bgr_viol=(0, 0, 255)):
    """
    Vẽ toàn bộ Bounding Box, Thẻ định danh và Huy hiệu tiếng Việt sắc nét 100%.
    Không bị lỗi font ??? và không vẽ class 'person' che khuất khung hình.
    """
    annotated = frame_bgr.copy()
    h, w = annotated.shape[:2]

    # Danh sách các badge text tiếng Việt cần vẽ đè bằng PIL
    pil_badges: list[dict[str, Any]] = []

    # 1. Vẽ các vật phẩm PPE (bỏ qua 'person')
    for obj in ppe_objects:
        cls_name = obj["name"].lower().strip()
        if cls_name == "person":
            continue  # Bỏ qua khung person to đùng

        ox1, oy1, ox2, oy2 = [int(v) for v in obj["box"]]
        
        # Tra cứu tên tiếng Việt
        vi_label, is_violation = VI_PPE_NAMES.get(cls_name, (cls_name.upper(), False))
        if 'no' in cls_name:
            is_violation = True

        # Kiểm tra xem loại PPE này có được bật giám sát không
        show_item = False
        if any(k in cls_name for k in ['helmet', 'hardhat']) and ppe_enabled.get('helmet', True):
            show_item = True
        elif any(k in cls_name for k in ['vest']) and ppe_enabled.get('vest', True):
            show_item = True
        elif any(k in cls_name for k in ['glove']) and ppe_enabled.get('gloves', False):
            show_item = True
        elif any(k in cls_name for k in ['glass', 'eyewear']) and ppe_enabled.get('glasses', False):
            show_item = True
        elif any(k in cls_name for k in ['boot']) and ppe_enabled.get('boots', False):
            show_item = True

        if not show_item:
            continue

        if is_violation:
            box_color = (40, 40, 235) # Đỏ rực
            tag_bg = (210, 30, 30)
            tag_fg = (255, 255, 255)
        else:
            box_color = (50, 205, 50) # Xanh lá
            tag_bg = (20, 140, 40)
            tag_fg = (255, 255, 255)

        # Vẽ khung vật phẩm
        cv2.rectangle(annotated, (ox1, oy1), (ox2, oy2), box_color, 2, cv2.LINE_AA)

        # Gom badge vào danh sách để vẽ một lần với Pillow
        pil_badges.append({
            'text': vi_label,
            'x': ox1,
            'y': max(0, oy1 - 18),
            'bg': tag_bg,
            'fg': tag_fg,
            'size': 11
        })

    # 2. Vẽ Khuôn Mặt & Thẻ Trạng Thái Nhân Viên
    for f in face_results:
        f_bbox = f['bbox']
        name = f['name']
        sim = f['similarity']
        status_text = f.get('status_str', 'ĐẠT TIỂU CHUẨN')
        is_viol = 'VI PHẠM' in status_text

        fx1, fy1, fx2, fy2 = [int(v) for v in f_bbox]

        # Chuẩn bị nội dung thẻ nhân sự & phân biệt Người Lạ vs Nhân Viên
        if name == "Unknown":
            display_name = "🚨 NGƯỜI LẠ"
            if is_viol:
                face_color = (30, 30, 230) # Đỏ rực nếu vi phạm PPE
                badge_bg = (200, 20, 20)
            else:
                face_color = (20, 120, 245) # Cam đậm cảnh báo an ninh
                badge_bg = (215, 85, 15)
        else:
            display_name = f"👤 {name} ({int(sim*100)}%)"
            face_color = bgr_viol if is_viol else bgr_pass
            badge_bg = (190, 20, 20) if is_viol else (20, 130, 50)

        # Vẽ khung góc công nghệ cao
        draw_tech_corners(annotated, (fx1, fy1, fx2, fy2), color=face_color, thickness=2, length=18)

        card_title = f"{display_name}  |  {status_text}"

        pil_badges.append({
            'text': card_title,
            'x': max(5, fx1 - 10),
            'y': max(5, fy1 - 25),
            'bg': badge_bg,
            'fg': (255, 255, 255),
            'size': 12
        })

    # 3. Vẽ toàn bộ Text tiếng Việt bằng Pillow (rất nhanh, khử răng cưa và sắc nét)
    if pil_badges:
        img_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        draw: Any = ImageDraw.Draw(pil_img)

        for b in pil_badges:
            font = get_font(int(b['size']))
            text = str(b['text'])
            bx = float(b['x'])
            by = float(b['y'])
            bbox = draw.textbbox((bx, by), text, font=font)
            pad_x = 6.0
            pad_y = 2.0
            rect = (bbox[0] - pad_x, bbox[1] - pad_y, bbox[2] + pad_x, bbox[3] + pad_y)

            # Vẽ nền badge bo góc nhẹ
            draw.rounded_rectangle(rect, radius=4, fill=b['bg'])
            draw.text((bx, by), text, font=font, fill=b['fg'])

        annotated = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    return annotated

def smart_fit_canvas(frame, target_w=680, target_h=360, fill_mode=False):
    """
    Co giãn khung hình camera khớp hoàn hảo vào khung hiển thị:
    - fill_mode=False (Mặc định chuẩn EHS): Giữ nguyên toàn cảnh 100% (không bao giờ bị cắt đầu, cắt cằm, mất đồ bảo hộ).
      Tự động đệm viền đen cân đối để bảo toàn tỉ lệ khung hình thực tế của camera.
    - fill_mode=True: Phóng to cắt giữa (Center-crop).
    """
    if frame is None or getattr(frame, 'size', 0) == 0:
        return np.zeros((max(60, target_h), max(60, target_w), 3), dtype=np.uint8)

    h, w = frame.shape[:2]
    tw = max(60, int(target_w))
    th = max(60, int(target_h))

    if fill_mode:
        scale = max(tw / w, th / h)
        nw = max(1, int(round(w * scale)))
        nh = max(1, int(round(h * scale)))
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)

        crop_x = max(0, (nw - tw) // 2)
        crop_y = max(0, (nh - th) // 2)
        canvas = resized[crop_y:crop_y + th, crop_x:crop_x + tw]
        if canvas.shape[0] != th or canvas.shape[1] != tw:
            canvas = cv2.resize(canvas, (tw, th), interpolation=cv2.INTER_LINEAR)
        return canvas
    else:
        scale = min(tw / w, th / h)
        nw = max(1, int(round(w * scale)))
        nh = max(1, int(round(h * scale)))
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)

        canvas = np.zeros((th, tw, 3), dtype=np.uint8)
        x_offset = max(0, (tw - nw) // 2)
        y_offset = max(0, (th - nh) // 2)
        canvas[y_offset:y_offset + nh, x_offset:x_offset + nw] = resized
        return canvas

def letterbox_canvas(frame_rgb, target_w=680, target_h=290):
    """ Hàm tương thích ngược: giữ nguyên tỉ lệ không cắt hình """
    return smart_fit_canvas(frame_rgb, target_w=target_w, target_h=target_h, fill_mode=False)

