import math
import hashlib
import base64
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw
try:
    from streamlit_drawable_canvas import st_canvas
    CANVAS_AVAILABLE = True
    CANVAS_IMPORT_ERROR = None
except Exception as e:
    st_canvas = None
    CANVAS_AVAILABLE = False
    CANVAS_IMPORT_ERROR = str(e)


# ============================================================
# Streamlit 기본 설정
# ============================================================
st.set_page_config(layout="wide", page_title="Heatmap Extractor")
st.title("Heatmap Extractor")
st.caption("heatmap 이미지 + 별도 업로드한 color bar 이미지를 사용하여 grid 기반 수치 테이블을 추출합니다.")
st.info("앱이 비어 보이거나 캔버스가 뜨지 않으면, 아래의 fallback ROI 입력 모드를 사용하세요.")
if not CANVAS_AVAILABLE:
    st.warning(f"streamlit_drawable_canvas import 실패: {CANVAS_IMPORT_ERROR}")


# ============================================================
# 세션 상태
# ============================================================
def init_state():
    defaults = {
        "heatmap_pil": None,
        "heatmap_name": None,
        "colorbar_pil": None,
        "colorbar_name": None,
        "heatmap_roi": None,
        "colorbar_roi": None,
        "colorbar_source": "uploaded_colorbar",
        "colorbar_direction": "horizontal",
        "colorbar_reverse_scale": False,
        "grid_long_df": pd.DataFrame(),
        "grid_df": pd.DataFrame(),
        "grid_preview": None,
        "colorbar_preview": None,
        "colorbar_values": None,
        "grid_meta": None,
        "heatmap_roi_manual": None,
        "colorbar_roi_manual": None,
        "heatmap_canvas_enabled": True,
        "colorbar_canvas_enabled": True,
        "heatmap_roi_skip_canvas_once": False,
        "colorbar_roi_skip_canvas_once": False,
        "heatmap_canvas_nonce": 0,
        "colorbar_canvas_nonce": 0,
        "heatmap_display_pil": None,
        "heatmap_display_scale": 1.0,
        "colorbar_display_pil": None,
        "colorbar_display_scale": 1.0,
        "heatmap_upload_sig": None,
        "colorbar_upload_sig": None,
        "heatmap_saved_rois": [None, None, None],
        "heatmap_active_box_idx": None,
        "heatmap_grid_target_idx": None,
        "heatmap_box_grid_settings": [
            {"grid_mode": "rows_cols", "n_cols": 12, "n_rows": 8, "cell_w": None, "cell_h": None},
            {"grid_mode": "rows_cols", "n_cols": 12, "n_rows": 8, "cell_w": None, "cell_h": None},
            {"grid_mode": "rows_cols", "n_cols": 12, "n_rows": 8, "cell_w": None, "cell_h": None},
        ],
        "heatmap_limit_height_enabled": False,
        "heatmap_display_height": 700,
        "colorbar_limit_height_enabled": False,
        "colorbar_display_height": 700,
        "preview_limit_height_enabled": False,
        "preview_display_height": 900,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


# ============================================================
# 유틸
# ============================================================
def pil_to_rgb_np(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("RGB"))


def np_to_pil(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(arr.astype(np.uint8))


# Helper: PIL image to base64 PNG string
def pil_to_base64_png(img: Image.Image) -> str:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ============================================================
# Image resizing utility for display
# ============================================================

def resize_for_canvas(
    img: Image.Image,
    max_display_width: Optional[int] = None,
    max_display_height: Optional[int] = None,
) -> Tuple[Image.Image, float]:
    w, h = img.size

    width_scale = (float(max_display_width) / float(w)) if (max_display_width is not None and w > max_display_width) else 1.0
    height_scale = (float(max_display_height) / float(h)) if (max_display_height is not None and h > max_display_height) else 1.0
    scale = min(width_scale, height_scale, 1.0)

    if scale >= 1.0:
        return img.copy(), 1.0

    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    return resized, scale


# Helper to show resized image with HTML/CSS resizing
def show_resized_image(
    img: Image.Image,
    caption: str = "",
    width: Optional[int] = None,
    limit_height_enabled: bool = False,
    display_height: Optional[int] = None,
):
    w, h = img.size

    if width is not None:
        target_w = int(width)
        target_h = max(1, int(round(h * (target_w / float(w)))))
    else:
        target_w = w
        target_h = h
        if limit_height_enabled and display_height is not None and h > int(display_height):
            scale = float(display_height) / float(h)
            target_h = max(1, int(round(h * scale)))
            target_w = max(1, int(round(w * scale)))

    img_b64 = pil_to_base64_png(img)
    html = f'''
    <div style="margin-bottom:0.25rem;">
        {f'<div style="font-size:0.9rem;color:#666;margin-bottom:0.25rem;">{caption}</div>' if caption else ''}
        <div style="width:{target_w}px;height:{target_h}px;overflow:hidden;display:block;">
            <img src="data:image/png;base64,{img_b64}" style="width:{target_w}px;height:{target_h}px;max-width:none;max-height:none;display:block;object-fit:fill;" />
        </div>
    </div>
    '''
    st.markdown(html, unsafe_allow_html=True)


# Helper to create a signature for uploaded file
def make_upload_signature(uploaded_file) -> Optional[str]:
    if uploaded_file is None:
        return None
    try:
        uploaded_file.seek(0)
        file_bytes = uploaded_file.read()
        uploaded_file.seek(0)
    except Exception:
        return None
    digest = hashlib.md5(file_bytes).hexdigest()
    return f"{uploaded_file.name}_{len(file_bytes)}_{digest}"


def extract_first_rect(json_data) -> Optional[Dict[str, int]]:
    if not json_data or "objects" not in json_data:
        return None
    for obj in json_data["objects"]:
        if obj.get("type") == "rect":
            left = int(round(obj.get("left", 0)))
            top = int(round(obj.get("top", 0)))
            width = int(round(obj.get("width", 0) * obj.get("scaleX", 1)))
            height = int(round(obj.get("height", 0) * obj.get("scaleY", 1)))
            return {
                "x1": left,
                "y1": top,
                "x2": left + width,
                "y2": top + height,
            }
    return None


def clamp_roi(roi: Dict[str, int], w: int, h: int) -> Dict[str, int]:
    x1 = max(0, min(w - 1, int(roi["x1"])))
    x2 = max(1, min(w, int(roi["x2"])))
    y1 = max(0, min(h - 1, int(roi["y1"])))
    y2 = max(1, min(h, int(roi["y2"])))
    if x2 <= x1:
        x2 = min(w, x1 + 1)
    if y2 <= y1:
        y2 = min(h, y1 + 1)
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


def crop_np(arr: np.ndarray, roi: Dict[str, int]) -> np.ndarray:
    return arr[roi["y1"]:roi["y2"], roi["x1"]:roi["x2"]].copy()


def draw_roi(img: Image.Image, roi: Optional[Dict[str, int]], color=(255, 0, 0), width=3) -> Image.Image:
    out = img.copy()
    if roi is None:
        return out
    d = ImageDraw.Draw(out)
    d.rectangle([roi["x1"], roi["y1"], roi["x2"], roi["y2"]], outline=color, width=width)
    return out


# Helper function: draw multiple ROIs on an image
def draw_multiple_rois(
    img: Image.Image,
    rois: List[Optional[Dict[str, int]]],
    colors: Optional[List[Tuple[int, int, int]]] = None,
    width: int = 3,
) -> Image.Image:
    out = img.copy()
    if colors is None:
        colors = [(255, 0, 0), (0, 180, 255), (0, 200, 80)]

    d = ImageDraw.Draw(out)
    for idx, roi in enumerate(rois):
        if roi is None:
            continue
        color = colors[idx % len(colors)]
        d.rectangle([roi["x1"], roi["y1"], roi["x2"], roi["y2"]], outline=color, width=width)
        tx = roi["x1"] + 6
        ty = max(0, roi["y1"] + 6)
        d.text((tx, ty), f"Box {idx+1}", fill=color)
    return out


def draw_grid_overlay(
    img: Image.Image,
    roi: Dict[str, int],
    xs: List[float],
    ys: List[float],
    centers: List[Tuple[float, float]],
) -> Image.Image:
    out = img.copy()
    d = ImageDraw.Draw(out)
    d.rectangle([roi["x1"], roi["y1"], roi["x2"], roi["y2"]], outline=(255, 0, 0), width=3)
    for x in xs:
        d.line([(x, roi["y1"]), (x, roi["y2"])], fill=(255, 255, 0), width=1)
    for y in ys:
        d.line([(roi["x1"], y), (roi["x2"], y)], fill=(255, 255, 0), width=1)
    for cx, cy in centers:
        r = 2
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(0, 255, 0))
    return out


# Helper to draw all saved heatmap boxes with their grids
def draw_saved_boxes_with_grids(
    img: Image.Image,
    rois: List[Optional[Dict[str, int]]],
    box_settings: List[Dict[str, object]],
    highlight_idx: Optional[int] = None,
) -> Image.Image:
    out = img.copy()
    for idx, roi in enumerate(rois):
        if roi is None:
            continue
        setting = box_settings[idx] if idx < len(box_settings) else {"grid_mode": "rows_cols", "n_cols": 12, "n_rows": 8, "cell_w": None, "cell_h": None}
        grid_mode = setting.get("grid_mode", "rows_cols")
        n_cols = int(setting.get("n_cols", 12) or 12)
        n_rows = int(setting.get("n_rows", 8) or 8)
        roi_w = roi["x2"] - roi["x1"]
        roi_h = roi["y2"] - roi["y1"]
        cell_w = float(setting.get("cell_w") or max(1.0, roi_w / max(1, n_cols)))
        cell_h = float(setting.get("cell_h") or max(1.0, roi_h / max(1, n_rows)))
        xs, ys = build_grid(roi, grid_mode, n_cols, n_rows, cell_w, cell_h)
        centers = [((xs[c] + xs[c + 1]) / 2, (ys[r] + ys[r + 1]) / 2) for r in range(len(ys) - 1) for c in range(len(xs) - 1)]
        out = draw_grid_overlay(out, roi, xs, ys, centers)
        if highlight_idx is not None and idx == highlight_idx:
            out = draw_roi(out, roi, color=(255, 255, 0), width=5)
    return out


def parse_labels(text: str, prefix: str, n: int) -> List[str]:
    items = [x.strip() for x in text.split(",") if x.strip()]
    if len(items) == n:
        return items
    return [f"{prefix}{i+1}" for i in range(n)]


def rgb_to_lab(colors_rgb: np.ndarray) -> np.ndarray:
    arr = colors_rgb.astype(np.uint8).reshape(-1, 1, 3)
    lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB)
    return lab.reshape(-1, 3).astype(np.float32)


def build_colorbar_profile(
    img: Image.Image,
    roi: Dict[str, int],
    direction: str,
    vmin: float,
    vmax: float,
    reverse_scale: bool,
    smooth_kernel: int,
) -> Tuple[np.ndarray, np.ndarray, Image.Image]:
    arr = pil_to_rgb_np(img)
    cropped = crop_np(arr, roi)
    h, w = cropped.shape[:2]

    if direction == "horizontal":
        line = cropped[h // 2, :, :]
    else:
        line = cropped[:, w // 2, :]

    if reverse_scale:
        line = line[::-1]

    if smooth_kernel > 1:
        k = max(1, int(smooth_kernel))
        if k % 2 == 0:
            k += 1
        if direction == "horizontal":
            tmp = cv2.GaussianBlur(line[np.newaxis, :, :], (k, 1), 0)[0]
        else:
            tmp = cv2.GaussianBlur(line[:, np.newaxis, :], (1, k), 0)[:, 0, :]
        line = tmp

    n = len(line)
    values = np.linspace(vmin, vmax, n, dtype=np.float32)

    preview = draw_roi(img, roi, color=(255, 0, 0), width=3)
    pdw = ImageDraw.Draw(preview)
    if direction == "horizontal":
        y = (roi["y1"] + roi["y2"]) / 2
        pdw.line([(roi["x1"], y), (roi["x2"], y)], fill=(0, 255, 0), width=3)
    else:
        x = (roi["x1"] + roi["x2"]) / 2
        pdw.line([(x, roi["y1"]), (x, roi["y2"])], fill=(0, 255, 0), width=3)

    return line.astype(np.uint8), values, preview


def build_grid(
    roi: Dict[str, int],
    mode: str,
    n_cols: int,
    n_rows: int,
    cell_w: float,
    cell_h: float,
) -> Tuple[List[float], List[float]]:
    width = roi["x2"] - roi["x1"]
    height = roi["y2"] - roi["y1"]

    if mode == "rows_cols":
        n_cols = max(1, int(n_cols))
        n_rows = max(1, int(n_rows))
        xs = np.linspace(roi["x1"], roi["x2"], n_cols + 1).tolist()
        ys = np.linspace(roi["y1"], roi["y2"], n_rows + 1).tolist()
    else:
        cell_w = max(1.0, float(cell_w))
        cell_h = max(1.0, float(cell_h))
        n_cols = max(1, int(round(width / cell_w)))
        n_rows = max(1, int(round(height / cell_h)))
        xs = [roi["x1"] + i * cell_w for i in range(n_cols)] + [roi["x2"]]
        ys = [roi["y1"] + j * cell_h for j in range(n_rows)] + [roi["y2"]]
        xs[0] = roi["x1"]
        ys[0] = roi["y1"]
        xs[-1] = roi["x2"]
        ys[-1] = roi["y2"]
    return xs, ys


def cell_mean_color(
    arr: np.ndarray,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    inner_margin_ratio: float,
) -> np.ndarray:
    w = x2 - x1
    h = y2 - y1
    mx = w * inner_margin_ratio
    my = h * inner_margin_ratio
    ix1 = int(round(x1 + mx))
    iy1 = int(round(y1 + my))
    ix2 = int(round(x2 - mx))
    iy2 = int(round(y2 - my))

    ix1 = max(0, min(arr.shape[1] - 1, ix1))
    iy1 = max(0, min(arr.shape[0] - 1, iy1))
    ix2 = max(ix1 + 1, min(arr.shape[1], ix2))
    iy2 = max(iy1 + 1, min(arr.shape[0], iy2))

    patch = arr[iy1:iy2, ix1:ix2]
    return patch.reshape(-1, 3).mean(axis=0)


def map_color_to_value(cell_rgb: np.ndarray, bar_line_rgb: np.ndarray, bar_values: np.ndarray) -> float:
    cell_lab = rgb_to_lab(np.array([cell_rgb], dtype=np.uint8))[0]
    bar_lab = rgb_to_lab(bar_line_rgb)
    dists = np.sum((bar_lab - cell_lab) ** 2, axis=1)
    idx = int(np.argmin(dists))
    return float(bar_values[idx])


def extract_heatmap_table(
    img: Image.Image,
    roi: Dict[str, int],
    xs: List[float],
    ys: List[float],
    row_labels: List[str],
    col_labels: List[str],
    bar_line_rgb: np.ndarray,
    bar_values: np.ndarray,
    inner_margin_ratio: float,
) -> Tuple[pd.DataFrame, pd.DataFrame, List[Tuple[float, float]]]:
    arr = pil_to_rgb_np(img)
    n_rows = len(ys) - 1
    n_cols = len(xs) - 1

    values = np.zeros((n_rows, n_cols), dtype=np.float32)
    records = []
    centers = []

    for r in range(n_rows):
        for c in range(n_cols):
            x1, x2 = xs[c], xs[c + 1]
            y1, y2 = ys[r], ys[r + 1]
            mean_rgb = cell_mean_color(arr, x1, y1, x2, y2, inner_margin_ratio)
            value = map_color_to_value(mean_rgb, bar_line_rgb, bar_values)
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            centers.append((cx, cy))
            values[r, c] = value
            records.append(
                {
                    "row_index": r + 1,
                    "col_index": c + 1,
                    "row_label": row_labels[r],
                    "col_label": col_labels[c],
                    "x_center": round(cx, 2),
                    "y_center": round(cy, 2),
                    "value": value,
                }
            )

    df_matrix = pd.DataFrame(values, index=row_labels, columns=col_labels)
    df_long = pd.DataFrame(records)
    return df_matrix, df_long, centers



def manual_roi_editor(label: str, state_key: str, img: Image.Image):
    st.markdown(f"##### {label} 수동 ROI 입력")
    w, h = img.size

    current = st.session_state.get(state_key)
    if current is None:
        current = {"x1": 0, "y1": 0, "x2": w, "y2": h}

    c1, c2, c3, c4 = st.columns(4)
    x1 = c1.number_input(f"{label} x1", min_value=0, max_value=max(0, w - 1), value=int(current["x1"]), step=1, key=f"manual_{state_key}_x1")
    y1 = c2.number_input(f"{label} y1", min_value=0, max_value=max(0, h - 1), value=int(current["y1"]), step=1, key=f"manual_{state_key}_y1")
    x2 = c3.number_input(f"{label} x2", min_value=1, max_value=w, value=int(current["x2"]), step=1, key=f"manual_{state_key}_x2")
    y2 = c4.number_input(f"{label} y2", min_value=1, max_value=h, value=int(current["y2"]), step=1, key=f"manual_{state_key}_y2")

    roi = clamp_roi({"x1": x1, "y1": y1, "x2": x2, "y2": y2}, w, h)
    st.session_state[state_key] = roi
    preview_img = draw_roi(img, roi)
    if state_key == "heatmap_roi":
        show_resized_image(
            preview_img,
            caption=f"{label} manual ROI preview",
            limit_height_enabled=bool(st.session_state.get("heatmap_limit_height_enabled", False)),
            display_height=int(st.session_state.get("heatmap_display_height", 700)),
        )
    else:
        show_resized_image(
            preview_img,
            caption=f"{label} manual ROI preview",
            limit_height_enabled=bool(st.session_state.get("colorbar_limit_height_enabled", False)),
            display_height=int(st.session_state.get("colorbar_display_height", 700)),
        )
    return roi


def roi_editor(label: str, state_key: str, img: Image.Image):
    st.markdown(f"#### {label}")
    w, h = img.size

    display_img_key = f"{state_key.replace('_roi', '')}_display_pil"
    display_scale_key = f"{state_key.replace('_roi', '')}_display_scale"

    display_img = st.session_state.get(display_img_key)
    display_scale = st.session_state.get(display_scale_key, 1.0)

    if state_key == "heatmap_roi":
        if st.session_state.get("heatmap_limit_height_enabled", False):
            display_img, display_scale = resize_for_canvas(
                img,
                max_display_width=None,
                max_display_height=int(st.session_state.get("heatmap_display_height", 700)),
            )
        else:
            display_img, display_scale = img.copy(), 1.0
    else:
        if st.session_state.get("colorbar_limit_height_enabled", False):
            display_img, display_scale = resize_for_canvas(
                img,
                max_display_width=None,
                max_display_height=int(st.session_state.get("colorbar_display_height", 700)),
            )
        else:
            display_img, display_scale = img.copy(), 1.0

    st.session_state[display_img_key] = display_img

    st.session_state[display_scale_key] = display_scale

    display_w, display_h = display_img.size
    skip_canvas_once_key = f"{state_key}_skip_canvas_once"
    canvas_nonce = st.session_state.get(f"{state_key.replace('_roi', '')}_canvas_nonce", 0)

    current_roi = st.session_state.get(state_key)

    # 기본은 manual로 시작해서 canvas가 자동으로 뜨지 않게 함
    default_mode = "manual" if current_roi is None else "adjust"

    if CANVAS_AVAILABLE:
        mode = st.radio(
            f"{label} 편집 모드",
            ["draw", "adjust", "manual"],
            index=["draw", "adjust", "manual"].index(default_mode),
            format_func=lambda x: {
                "draw": "드래그로 ROI 지정",
                "adjust": "버튼으로 미세조정",
                "manual": "수동 숫자 입력",
            }[x],
            horizontal=True,
            key=f"mode_{state_key}_{canvas_nonce}",
        )
    else:
        mode = st.radio(
            f"{label} 편집 모드",
            ["adjust", "manual"],
            index=0 if current_roi is not None else 1,
            format_func=lambda x: {
                "adjust": "버튼으로 미세조정",
                "manual": "수동 숫자 입력",
            }[x],
            horizontal=True,
            key=f"mode_{state_key}_{canvas_nonce}",
        )

    if mode == "manual":
        return manual_roi_editor(label, state_key, img)

    if mode == "draw":
        st.caption("드래그로 ROI를 지정한 뒤에는 `버튼으로 미세조정` 모드로 전환하세요.")
        try:
            canvas_result = st_canvas(
                fill_color="rgba(255, 0, 0, 0.10)",
                stroke_width=2,
                stroke_color="#ff0000",
                background_image=display_img,
                update_streamlit=True,
                height=display_h,
                width=display_w,
                drawing_mode="rect",
                key=f"canvas_{state_key}_{display_w}_{display_h}_{canvas_nonce}",
            )

            rect = extract_first_rect(canvas_result.json_data)
            skip_canvas_once = st.session_state.get(skip_canvas_once_key, False)
            if skip_canvas_once:
                st.session_state[skip_canvas_once_key] = False
            elif rect is not None:
                rect = {
                    "x1": int(round(rect["x1"] / display_scale)),
                    "y1": int(round(rect["y1"] / display_scale)),
                    "x2": int(round(rect["x2"] / display_scale)),
                    "y2": int(round(rect["y2"] / display_scale)),
                }
                st.session_state[state_key] = clamp_roi(rect, w, h)
        except Exception as e:
            st.warning(f"캔버스 로드 실패. 수동 ROI 입력 모드로 전환합니다: {e}")
            return manual_roi_editor(label, state_key, img)

    roi = st.session_state[state_key]
    if roi is None:
        st.info("드래그 모드로 ROI를 지정하거나, 수동 숫자 입력 모드를 사용하세요.")
        if state_key == "heatmap_roi":
            show_resized_image(
                img,
                caption=f"{label} original image",
                limit_height_enabled=bool(st.session_state.get("heatmap_limit_height_enabled", False)),
                display_height=int(st.session_state.get("heatmap_display_height", 700)),
            )
        else:
            show_resized_image(
                img,
                caption=f"{label} original image",
                limit_height_enabled=bool(st.session_state.get("colorbar_limit_height_enabled", False)),
                display_height=int(st.session_state.get("colorbar_display_height", 700)),
            )
        return None

    if state_key == "heatmap_roi":
        st.markdown("##### Heatmap ROI box slots")
        saved_rois = st.session_state.get("heatmap_saved_rois", [None, None, None])
        active_box_idx = st.session_state.get("heatmap_active_box_idx", None)

        s1, s2, s3 = st.columns(3)
        with s1:
            status = "설정됨" if saved_rois[0] is not None else "비어있음"
            active = " (선택중)" if active_box_idx == 0 else ""
            st.caption(f"Box 1: {status}{active}")
            if st.button("현재 ROI를 Box 1에 저장", key="save_heatmap_box_1"):
                saved_rois[0] = dict(st.session_state[state_key])
                active_box_idx = 0
                st.session_state[skip_canvas_once_key] = True
                st.session_state["heatmap_canvas_nonce"] += 1
        with s2:
            status = "설정됨" if saved_rois[1] is not None else "비어있음"
            active = " (선택중)" if active_box_idx == 1 else ""
            st.caption(f"Box 2: {status}{active}")
            if st.button("현재 ROI를 Box 2에 저장", key="save_heatmap_box_2"):
                saved_rois[1] = dict(st.session_state[state_key])
                active_box_idx = 1
                st.session_state[skip_canvas_once_key] = True
                st.session_state["heatmap_canvas_nonce"] += 1
        with s3:
            status = "설정됨" if saved_rois[2] is not None else "비어있음"
            active = " (선택중)" if active_box_idx == 2 else ""
            st.caption(f"Box 3: {status}{active}")
            if st.button("현재 ROI를 Box 3에 저장", key="save_heatmap_box_3"):
                saved_rois[2] = dict(st.session_state[state_key])
                active_box_idx = 2
                st.session_state[skip_canvas_once_key] = True
                st.session_state["heatmap_canvas_nonce"] += 1

        l1, l2, l3, l4 = st.columns(4)
        with l1:
            if st.button("Box 1 불러오기", key="load_heatmap_box_1") and saved_rois[0] is not None:
                st.session_state[state_key] = dict(saved_rois[0])
                active_box_idx = 0
                st.session_state[skip_canvas_once_key] = True
                st.session_state["heatmap_canvas_nonce"] += 1
        with l2:
            if st.button("Box 2 불러오기", key="load_heatmap_box_2") and saved_rois[1] is not None:
                st.session_state[state_key] = dict(saved_rois[1])
                active_box_idx = 1
                st.session_state[skip_canvas_once_key] = True
                st.session_state["heatmap_canvas_nonce"] += 1
        with l3:
            if st.button("Box 3 불러오기", key="load_heatmap_box_3") and saved_rois[2] is not None:
                st.session_state[state_key] = dict(saved_rois[2])
                active_box_idx = 2
                st.session_state[skip_canvas_once_key] = True
                st.session_state["heatmap_canvas_nonce"] += 1
        with l4:
            if st.button("Box 전체 초기화", key="clear_heatmap_boxes"):
                saved_rois = [None, None, None]
                active_box_idx = None
                st.session_state["heatmap_grid_target_idx"] = None
                st.session_state["heatmap_box_grid_settings"] = [
                    {"grid_mode": "rows_cols", "n_cols": 12, "n_rows": 8, "cell_w": None, "cell_h": None},
                    {"grid_mode": "rows_cols", "n_cols": 12, "n_rows": 8, "cell_w": None, "cell_h": None},
                    {"grid_mode": "rows_cols", "n_cols": 12, "n_rows": 8, "cell_w": None, "cell_h": None},
                ]
                st.session_state[skip_canvas_once_key] = True
                st.session_state["heatmap_canvas_nonce"] += 1

        st.session_state["heatmap_saved_rois"] = saved_rois
        st.session_state["heatmap_active_box_idx"] = active_box_idx
        if active_box_idx is not None and 0 <= active_box_idx < len(saved_rois) and saved_rois[active_box_idx] is not None:
            st.session_state[state_key] = dict(saved_rois[active_box_idx])

        saved_overlay = draw_multiple_rois(img, saved_rois)
        if active_box_idx is not None and saved_rois[active_box_idx] is not None:
            saved_overlay = draw_roi(saved_overlay, saved_rois[active_box_idx], color=(255, 255, 0), width=5)
        show_resized_image(
            saved_overlay,
            caption="saved heatmap box preview",
            limit_height_enabled=bool(st.session_state.get("heatmap_limit_height_enabled", False)),
            display_height=int(st.session_state.get("heatmap_display_height", 700)),
        )

        roi = st.session_state[state_key]

    st.write("현재 ROI:", roi)
    step = st.number_input(
        f"{label} 미세조정 step(px)",
        min_value=1,
        value=1,
        step=1,
        key=f"step_{state_key}",
    )
    changed = False

    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Left -", key=f"left_minus_{state_key}"):
        roi["x1"] -= step
        changed = True
    if c2.button("Left +", key=f"left_plus_{state_key}"):
        roi["x1"] += step
        changed = True
    if c3.button("Right -", key=f"right_minus_{state_key}"):
        roi["x2"] -= step
        changed = True
    if c4.button("Right +", key=f"right_plus_{state_key}"):
        roi["x2"] += step
        changed = True

    c5, c6, c7, c8 = st.columns(4)
    if c5.button("Top -", key=f"top_minus_{state_key}"):
        roi["y1"] -= step
        changed = True
    if c6.button("Top +", key=f"top_plus_{state_key}"):
        roi["y1"] += step
        changed = True
    if c7.button("Bottom -", key=f"bottom_minus_{state_key}"):
        roi["y2"] -= step
        changed = True
    if c8.button("Bottom +", key=f"bottom_plus_{state_key}"):
        roi["y2"] += step
        changed = True

    c9, c10, c11, c12 = st.columns(4)
    if c9.button("Move ←", key=f"move_left_{state_key}"):
        roi["x1"] -= step
        roi["x2"] -= step
        changed = True
    if c10.button("Move →", key=f"move_right_{state_key}"):
        roi["x1"] += step
        roi["x2"] += step
        changed = True
    if c11.button("Move ↑", key=f"move_up_{state_key}"):
        roi["y1"] -= step
        roi["y2"] -= step
        changed = True
    if c12.button("Move ↓", key=f"move_down_{state_key}"):
        roi["y1"] += step
        roi["y2"] += step
        changed = True

    st.session_state[state_key] = clamp_roi(roi, w, h)
    if changed:
        st.session_state[skip_canvas_once_key] = True
        if state_key == "heatmap_roi":
            active_box_idx = st.session_state.get("heatmap_active_box_idx", None)
            saved_rois = st.session_state.get("heatmap_saved_rois", [None, None, None])
            if active_box_idx is not None:
                saved_rois[active_box_idx] = dict(st.session_state[state_key])
                st.session_state["heatmap_saved_rois"] = saved_rois

    if state_key == "heatmap_roi":
        saved_rois = st.session_state.get("heatmap_saved_rois", [None, None, None])
        active_box_idx = st.session_state.get("heatmap_active_box_idx", None)
        preview_img = draw_multiple_rois(img, saved_rois)
        current_roi = st.session_state[state_key]
        if current_roi is not None:
            preview_img = draw_roi(preview_img, current_roi, color=(255, 255, 0), width=5)
        if active_box_idx is not None and 0 <= active_box_idx < len(saved_rois):
            st.caption(f"현재 미세조정 대상: Box {active_box_idx + 1}")
    else:
        preview_img = draw_roi(img, st.session_state[state_key])

    if state_key == "heatmap_roi":
        show_resized_image(
            preview_img,
            caption=f"{label} preview",
            limit_height_enabled=bool(st.session_state.get("heatmap_limit_height_enabled", False)),
            display_height=int(st.session_state.get("heatmap_display_height", 700)),
        )
    else:
        show_resized_image(
            preview_img,
            caption=f"{label} preview",
            limit_height_enabled=bool(st.session_state.get("colorbar_limit_height_enabled", False)),
            display_height=int(st.session_state.get("colorbar_display_height", 700)),
        )
    return st.session_state[state_key]


# ============================================================
# 업로드 영역
# ============================================================
left_top, right_top = st.columns(2)

with left_top:
    st.subheader("1) Heatmap 이미지")
    heatmap_file = st.file_uploader(
        "heatmap 이미지 업로드",
        type=["png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp"],
        key="heatmap_upload",
    )
    if heatmap_file is not None:
        heatmap_sig = make_upload_signature(heatmap_file)
        if heatmap_sig != st.session_state.get("heatmap_upload_sig"):
            heatmap_file.seek(0)
            uploaded_heatmap = Image.open(BytesIO(heatmap_file.read())).convert("RGB")
            heatmap_file.seek(0)
            if st.session_state.get("heatmap_limit_height_enabled", False):
                display_heatmap, display_scale = resize_for_canvas(
                    uploaded_heatmap,
                    max_display_width=None,
                    max_display_height=int(st.session_state.get("heatmap_display_height", 700)),
                )
            else:
                display_heatmap, display_scale = uploaded_heatmap.copy(), 1.0

            st.session_state.heatmap_pil = uploaded_heatmap
            st.session_state.heatmap_display_pil = display_heatmap
            st.session_state.heatmap_display_scale = display_scale
            st.session_state.heatmap_name = heatmap_file.name
            st.session_state.heatmap_upload_sig = heatmap_sig
            st.session_state.heatmap_roi = None
            st.session_state.heatmap_roi_skip_canvas_once = False
            st.session_state.heatmap_canvas_nonce += 1
            st.session_state.grid_df = pd.DataFrame()
            st.session_state.grid_long_df = pd.DataFrame()
            st.session_state.grid_preview = None
            st.session_state.grid_meta = None

with right_top:
    st.subheader("2) Color bar 이미지")
    colorbar_file = st.file_uploader(
        "color bar 이미지를 반드시 업로드하세요",
        type=["png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp"],
        key="colorbar_upload",
    )
    if colorbar_file is not None:
        colorbar_sig = make_upload_signature(colorbar_file)
        if colorbar_sig != st.session_state.get("colorbar_upload_sig"):
            colorbar_file.seek(0)
            uploaded_colorbar = Image.open(BytesIO(colorbar_file.read())).convert("RGB")
            colorbar_file.seek(0)
            if st.session_state.get("colorbar_limit_height_enabled", False):
                display_colorbar, display_scale = resize_for_canvas(
                    uploaded_colorbar,
                    max_display_width=None,
                    max_display_height=int(st.session_state.get("colorbar_display_height", 700)),
                )
            else:
                display_colorbar, display_scale = uploaded_colorbar.copy(), 1.0
            st.session_state.colorbar_pil = uploaded_colorbar
            st.session_state.colorbar_display_pil = display_colorbar
            st.session_state.colorbar_display_scale = display_scale
            st.session_state.colorbar_name = colorbar_file.name
            st.session_state.colorbar_upload_sig = colorbar_sig
            st.session_state.colorbar_roi = None
            st.session_state.colorbar_roi_skip_canvas_once = False
            st.session_state.colorbar_canvas_nonce += 1
            st.session_state.colorbar_preview = None
            st.session_state.colorbar_values = None

if st.session_state.heatmap_pil is None:
    st.warning("먼저 heatmap 이미지를 업로드하세요.")
    st.markdown("현재 화면이 비어 보이면, 본문 상단의 업로드 영역에 이미지를 넣어야 합니다.")
    st.stop()

if st.session_state.colorbar_pil is None:
    st.warning("color bar 이미지를 반드시 업로드하세요. heatmap 내부 color bar 선택은 이제 사용하지 않습니다.")
    st.stop()

# ============================================================
# 표시 크기 설정
# ============================================================
st.markdown("---")
st.subheader("표시 크기 설정")
size1, size2, size3 = st.columns(3)

with size1:
    st.markdown("##### Heatmap 표시 크기")
    st.caption("기본은 원본 그대로 표시합니다. 너무 크면 세로 길이만 제한하세요.")
    st.session_state.heatmap_limit_height_enabled = st.checkbox(
        "Heatmap 세로 길이 조정 사용",
        value=bool(st.session_state.get("heatmap_limit_height_enabled", False)),
        key="heatmap_limit_height_enabled_input",
    )
    st.session_state.heatmap_display_height = st.number_input(
        "Heatmap 표시 높이(px)",
        min_value=200,
        max_value=2400,
        value=int(st.session_state.get("heatmap_display_height", 700)),
        step=50,
        key="heatmap_display_height_input",
    )

with size2:
    st.markdown("##### Color bar 표시 크기")
    st.caption("기본은 원본 그대로 표시합니다. 너무 크면 세로 길이만 제한하세요.")
    st.session_state.colorbar_limit_height_enabled = st.checkbox(
        "Color bar 세로 길이 조정 사용",
        value=bool(st.session_state.get("colorbar_limit_height_enabled", False)),
        key="colorbar_limit_height_enabled_input",
    )
    st.session_state.colorbar_display_height = st.number_input(
        "Color bar 표시 높이(px)",
        min_value=100,
        max_value=2400,
        value=int(st.session_state.get("colorbar_display_height", 700)),
        step=50,
        key="colorbar_display_height_input",
    )

with size3:
    st.markdown("##### Preview 표시 크기")
    st.caption("기본은 원본 그대로 표시합니다. 너무 크면 세로 길이만 제한하세요.")
    st.session_state.preview_limit_height_enabled = st.checkbox(
        "Preview 세로 길이 조정 사용",
        value=bool(st.session_state.get("preview_limit_height_enabled", False)),
        key="preview_limit_height_enabled_input",
    )
    st.session_state.preview_display_height = st.number_input(
        "Preview 표시 높이(px)",
        min_value=200,
        max_value=3000,
        value=int(st.session_state.get("preview_display_height", 900)),
        step=50,
        key="preview_display_height_input",
    )

# ============================================================
# ROI 선택
# ============================================================
st.markdown("---")
st.subheader("디버그 정보")
dbg1, dbg2, dbg3 = st.columns(3)
dbg1.write({"heatmap_loaded": st.session_state.heatmap_pil is not None, "colorbar_loaded": st.session_state.colorbar_pil is not None})
dbg2.write({"canvas_available": CANVAS_AVAILABLE})
dbg3.write({"heatmap_size": st.session_state.heatmap_pil.size if st.session_state.heatmap_pil else None})
st.markdown("---")
col_a, col_b = st.columns(2)

with col_a:
    heatmap_roi = roi_editor("Heatmap ROI", "heatmap_roi", st.session_state.heatmap_pil)

with col_b:

    st.session_state.colorbar_source = "uploaded_colorbar"

    st.caption("color bar 이미지는 별도 업로드만 허용됩니다.")
    st.session_state.colorbar_direction = st.radio(
        "Color bar 방향",
        ["horizontal", "vertical"],
        index=0 if st.session_state.get("colorbar_direction", "horizontal") == "horizontal" else 1,
        format_func=lambda x: "가로형" if x == "horizontal" else "세로형",
        horizontal=True,
        key="colorbar_direction_selector_top",
    )

    colorbar_img_for_roi = st.session_state.colorbar_pil

    colorbar_roi = roi_editor("Color bar ROI", "colorbar_roi", colorbar_img_for_roi)


# ============================================================
# Color bar 샘플링 설정
# ============================================================
st.markdown("---")
st.subheader("3) Color bar 수치 설정")
cb1, cb2, cb3, cb4, cb5 = st.columns(5)
colorbar_direction = cb1.radio(
    "bar 방향",
    ["horizontal", "vertical"],
    index=0 if st.session_state.get("colorbar_direction", "horizontal") == "horizontal" else 1,
    horizontal=True,
    key="colorbar_direction_selector_bottom",
)
st.session_state.colorbar_direction = colorbar_direction
bar_min = cb2.number_input("최소값", value=0.0, step=0.1, format="%.6f")
bar_max = cb3.number_input("최대값", value=1.0, step=0.1, format="%.6f")
reverse_scale = cb4.checkbox(
    "색상 방향 뒤집기",
    value=bool(st.session_state.get("colorbar_reverse_scale", False)),
    key="colorbar_reverse_scale_checkbox",
)
st.session_state.colorbar_reverse_scale = reverse_scale
smooth_kernel = cb5.number_input("line smoothing", min_value=1, value=5, step=2)

bar_line_rgb = None
bar_values = None

if colorbar_roi is not None:
    colorbar_img = colorbar_img_for_roi
    try:
        bar_line_rgb, bar_values, cb_preview = build_colorbar_profile(
            colorbar_img,
            colorbar_roi,
            colorbar_direction,
            float(bar_min),
            float(bar_max),
            bool(reverse_scale),
            int(smooth_kernel),
        )
        st.session_state.colorbar_values = bar_values
        st.session_state.colorbar_preview = cb_preview
        p1, p2 = st.columns(2)
        with p1:
            show_resized_image(
                cb_preview,
                caption="color bar sampling preview",
                limit_height_enabled=bool(st.session_state.get("colorbar_limit_height_enabled", False)),
                display_height=int(st.session_state.get("colorbar_display_height", 700)),
            )
        with p2:
            sampled_line_img = np_to_pil(
                bar_line_rgb.reshape(1, -1, 3) if colorbar_direction == "horizontal" else bar_line_rgb.reshape(-1, 1, 3)
            )
            show_resized_image(
                sampled_line_img,
                caption="sampled line colors",
                limit_height_enabled=bool(st.session_state.get("colorbar_limit_height_enabled", False)),
                display_height=int(st.session_state.get("colorbar_display_height", 700)),
            )
    except Exception as e:
        st.error(f"color bar profile 생성 실패: {e}")


# ============================================================
# Grid 설정
# ============================================================
st.markdown("---")
st.subheader("4) Heatmap grid 설정")

if heatmap_roi is None:
    st.info("먼저 Heatmap ROI를 선택하세요.")
    st.stop()

saved_heatmap_rois = st.session_state.get("heatmap_saved_rois", [None, None, None])
box_grid_settings = st.session_state.get("heatmap_box_grid_settings", [
    {"grid_mode": "rows_cols", "n_cols": 12, "n_rows": 8, "cell_w": None, "cell_h": None},
    {"grid_mode": "rows_cols", "n_cols": 12, "n_rows": 8, "cell_w": None, "cell_h": None},
    {"grid_mode": "rows_cols", "n_cols": 12, "n_rows": 8, "cell_w": None, "cell_h": None},
])

available_box_indices = [idx for idx, roi in enumerate(saved_heatmap_rois) if roi is not None]
if available_box_indices:
    default_target_idx = st.session_state.get("heatmap_grid_target_idx", available_box_indices[0])
    if default_target_idx not in available_box_indices:
        default_target_idx = available_box_indices[0]
    selected_box_idx = st.radio(
        "행/열 설정 대상 Box",
        available_box_indices,
        index=available_box_indices.index(default_target_idx),
        format_func=lambda x: f"Box {x + 1}",
        horizontal=True,
        key="heatmap_grid_target_selector",
    )
    st.session_state["heatmap_grid_target_idx"] = selected_box_idx
    heatmap_roi = saved_heatmap_rois[selected_box_idx]
    current_box_setting = box_grid_settings[selected_box_idx]
else:
    selected_box_idx = None
    current_box_setting = {"grid_mode": "rows_cols", "n_cols": 12, "n_rows": 8, "cell_w": None, "cell_h": None}

roi_w = heatmap_roi["x2"] - heatmap_roi["x1"]
roi_h = heatmap_roi["y2"] - heatmap_roi["y1"]

g1, g2, g3, g4 = st.columns(4)
default_grid_mode = current_box_setting.get("grid_mode", "rows_cols")
if default_grid_mode not in ["rows_cols", "cell_size"]:
    default_grid_mode = "rows_cols"

grid_mode = g1.radio(
    "grid 분할 방식",
    ["rows_cols", "cell_size"],
    index=0 if default_grid_mode == "rows_cols" else 1,
    format_func=lambda x: "행/열 개수로 분할" if x == "rows_cols" else "cell width/height로 분할",
    key=f"grid_mode_box_{selected_box_idx if selected_box_idx is not None else 'none'}",
)
inner_margin_ratio = g2.slider("셀 내부 샘플링 margin 비율", 0.0, 0.45, 0.15, 0.01)

if grid_mode == "rows_cols":
    n_cols = g3.number_input(
        "열 개수",
        min_value=1,
        value=int(current_box_setting.get("n_cols", 12) or 12),
        step=1,
        key=f"n_cols_box_{selected_box_idx if selected_box_idx is not None else 'none'}",
    )
    n_rows = g4.number_input(
        "행 개수",
        min_value=1,
        value=int(current_box_setting.get("n_rows", 8) or 8),
        step=1,
        key=f"n_rows_box_{selected_box_idx if selected_box_idx is not None else 'none'}",
    )
    cell_w = roi_w / max(1, int(n_cols))
    cell_h = roi_h / max(1, int(n_rows))
else:
    default_cell_w = float(current_box_setting.get("cell_w") or max(1.0, roi_w / 12))
    default_cell_h = float(current_box_setting.get("cell_h") or max(1.0, roi_h / 8))
    cell_w = g3.number_input(
        "cell width(px)",
        min_value=1.0,
        value=default_cell_w,
        step=1.0,
        key=f"cell_w_box_{selected_box_idx if selected_box_idx is not None else 'none'}",
    )
    cell_h = g4.number_input(
        "cell height(px)",
        min_value=1.0,
        value=default_cell_h,
        step=1.0,
        key=f"cell_h_box_{selected_box_idx if selected_box_idx is not None else 'none'}",
    )
    n_cols = max(1, int(round(roi_w / float(cell_w))))
    n_rows = max(1, int(round(roi_h / float(cell_h))))

if selected_box_idx is not None:
    box_grid_settings[selected_box_idx] = {
        "grid_mode": grid_mode,
        "n_cols": int(n_cols),
        "n_rows": int(n_rows),
        "cell_w": float(cell_w),
        "cell_h": float(cell_h),
    }
    st.session_state["heatmap_box_grid_settings"] = box_grid_settings

lab1, lab2 = st.columns(2)
col_labels_text = lab1.text_area(
    "열 라벨 (쉼표 구분, 비워두면 Col1, Col2 ...)",
    value="",
    height=120,
)
row_labels_text = lab2.text_area(
    "행 라벨 (쉼표 구분, 비워두면 Row1, Row2 ...)",
    value="",
    height=120,
)

xs, ys = build_grid(
    heatmap_roi,
    grid_mode,
    int(n_cols),
    int(n_rows),
    float(cell_w),
    float(cell_h),
)

row_labels = parse_labels(row_labels_text, "Row", len(ys) - 1)
col_labels = parse_labels(col_labels_text, "Col", len(xs) - 1)
centers_preview = [((xs[c] + xs[c + 1]) / 2, (ys[r] + ys[r + 1]) / 2) for r in range(len(ys) - 1) for c in range(len(xs) - 1)]

if available_box_indices:
    grid_overlay = draw_saved_boxes_with_grids(
        st.session_state.heatmap_pil,
        saved_heatmap_rois,
        box_grid_settings,
        highlight_idx=selected_box_idx,
    )
else:
    grid_overlay = draw_grid_overlay(st.session_state.heatmap_pil, heatmap_roi, xs, ys, centers_preview)

show_resized_image(
    grid_overlay,
    caption="grid preview",
    limit_height_enabled=bool(st.session_state.get("preview_limit_height_enabled", False)),
    display_height=int(st.session_state.get("preview_display_height", 900)),
)


# ============================================================
# 추출 실행
# ============================================================
st.markdown("---")
st.subheader("5) 추출 실행")
extract_btn = st.button("Apply / 표 생성", type="primary")

if extract_btn:
    if bar_line_rgb is None or bar_values is None or colorbar_roi is None or heatmap_roi is None:
        st.error("heatmap ROI와 color bar ROI를 먼저 지정하고, 업로드한 color bar 이미지에서 profile을 정상적으로 생성해야 합니다.")
    else:
        try:
            df_matrix, df_long, centers = extract_heatmap_table(
                st.session_state.heatmap_pil,
                heatmap_roi,
                xs,
                ys,
                row_labels,
                col_labels,
                bar_line_rgb,
                bar_values,
                float(inner_margin_ratio),
            )
            preview = draw_grid_overlay(st.session_state.heatmap_pil, heatmap_roi, xs, ys, centers)
            st.session_state.grid_df = df_matrix
            st.session_state.grid_long_df = df_long
            st.session_state.grid_preview = preview
            st.session_state.grid_meta = {
                "heatmap_name": st.session_state.heatmap_name,
                "colorbar_source": st.session_state.colorbar_source,
                "bar_min": float(bar_min),
                "bar_max": float(bar_max),
                "reverse_scale": bool(reverse_scale),
                "colorbar_direction": colorbar_direction,
                "n_rows": len(row_labels),
                "n_cols": len(col_labels),
                "heatmap_roi": heatmap_roi,
                "colorbar_roi": colorbar_roi,
            }
            st.success("표 생성 완료")
        except Exception as e:
            st.error(f"추출 실패: {e}")


# ============================================================
# 결과 표시
# ============================================================
if not st.session_state.grid_df.empty:
    st.markdown("---")
    st.subheader("6) 결과")
    r1, r2 = st.columns(2)
    with r1:
        show_resized_image(
            st.session_state.grid_preview,
            caption="extraction preview",
            limit_height_enabled=bool(st.session_state.get("preview_limit_height_enabled", False)),
            display_height=int(st.session_state.get("preview_display_height", 900)),
        )
    with r2:
        st.json(st.session_state.grid_meta)

    st.markdown("#### Matrix table")
    st.dataframe(st.session_state.grid_df, use_container_width=True)

    st.markdown("#### Long table")
    st.dataframe(st.session_state.grid_long_df, use_container_width=True, height=400)

    csv_matrix = st.session_state.grid_df.to_csv(index=True).encode("utf-8-sig")
    csv_long = st.session_state.grid_long_df.to_csv(index=False).encode("utf-8-sig")

    d1, d2 = st.columns(2)
    d1.download_button(
        "Download matrix CSV",
        data=csv_matrix,
        file_name="heatmap_matrix.csv",
        mime="text/csv",
    )
    d2.download_button(
        "Download long CSV",
        data=csv_long,
        file_name="heatmap_long.csv",
        mime="text/csv",
    )


# ============================================================
# 사용 팁
# ============================================================
with st.expander("사용 팁"):
    st.markdown(
        """
1. **Heatmap ROI**: 실제 셀 영역만 포함되도록 먼저 잡습니다. 축 라벨/덴드로그램/범례는 가급적 제외하세요.
2. **Color bar ROI**: 색상 막대만 포함되게 잡습니다. 가능하면 숫자 라벨은 제외하세요.
2-0. Color bar가 가로형인지 세로형인지 먼저 선택한 뒤 ROI를 잡고 값을 설정하세요.
2-1. ROI를 한번 잡은 뒤에는 `버튼으로 미세조정` 모드에서 좌우/상하 버튼으로 위치를 조정하세요.
3. color bar 이미지는 반드시 별도로 업로드하고, 그 이미지에서 ROI를 잡아야 합니다.
3-1. Heatmap ROI에서는 현재 ROI를 Box 1/2/3에 저장해 두고, 필요할 때 다시 불러와 사용할 수 있습니다.
3-2. 저장된 각 Box는 아래 grid 설정 구역에서 선택한 뒤, Box별로 서로 다른 행/열 개수 또는 cell 크기를 지정할 수 있습니다.
4. color bar가 세로 막대면 `vertical`, 가로 막대면 `horizontal`을 고르세요.
5. 값이 반대로 나오면 `색상 방향 뒤집기`를 켜세요.
6. grid는 `행/열 개수` 또는 `cell width/height` 둘 중 하나로 설정할 수 있습니다.
7. 셀 내부 평균 색을 쓸 때 가장자리 경계선 영향이 크면 `margin 비율`을 조금 올리세요.
8. 표시 이미지는 기본적으로 원본 그대로 보여주고, `세로 길이 조정 사용`을 켠 경우에만 표시 높이(px)를 기준으로 축소합니다.
9. 세로 길이를 조정하면 가로 길이도 원본 비율에 맞춰 자동으로 함께 줄어듭니다.
        """
    )

# streamlit run /Users/kogeon/python_projects_path/LNPDB_Articles_Extraction/4_Extract_Exp_Vals/Exp_Vals_From_Figs/heatmap/extract_from_heatmap.py
