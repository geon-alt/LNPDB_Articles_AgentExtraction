import streamlit as st
import cv2
import numpy as np
import pandas as pd
from PIL import Image
import json
import hashlib
from io import BytesIO
from streamlit_image_coordinates import streamlit_image_coordinates
import sys, os
from pathlib import Path

# =========================
# Gemini API 설정
# =========================
CURRENT_DIR = Path(__file__).resolve().parent

PROJECT_ROOT = None
for p in [CURRENT_DIR, *CURRENT_DIR.parents]:
    if (p / "find_api.py").exists():
        PROJECT_ROOT = p
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
        break

API_IMPORT_ERROR = None

try:
    from find_api import find_api_key_file, get_vertexai_client
    from google.genai import types  # noqa: F401
    API_AVAILABLE = True
except Exception as e:
    API_AVAILABLE = False
    API_IMPORT_ERROR = str(e)

# =========================
# Streamlit 기본 설정
# =========================
st.set_page_config(layout="wide", page_title="LNPDB Plot Extractor")

# =========================
# 세션 상태 초기화
# =========================
def init_session_state():
    defaults = {
        "uploaded_file_hash": None,
        "uploaded_file_name": None,
        "uploaded_bytes": None,
        "image_cv": None,
        "image_pil": None,

        "axis_y": 200,
        "y_max_pixel": 50,
        "baseline_y": 200,
        "y_max": 100.0,
        "y_min": 0.0,

        "plot_type": "Unknown",
        "x_labels_input": "",
        "df_extracted": pd.DataFrame(
            columns=["selected", "figure_name", "X_Label", "Value", "Type", "x_pixel", "y_pixel"]
        ),

        "last_click_x": None,
        "last_click_y": None,
        "last_click_signature": None,
        "last_applied_click_signature": None,

        "input_axis_y": 200,
        "input_y_max_pixel": 50,
        "input_baseline_y": 200,
        "figure_name": "",
        "cursor_y": None,
        "cursor_step": 1,
        "selected_row_idx_memory": None,
    }

    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_session_state()

# =========================
# 유틸
# =========================
def file_to_hash(file_bytes: bytes) -> str:
    return hashlib.md5(file_bytes).hexdigest()

def load_image_from_bytes(file_bytes: bytes):
    np_arr = np.frombuffer(file_bytes, dtype=np.uint8)
    image_cv = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if image_cv is None:
        raise ValueError("OpenCV로 이미지를 디코딩하지 못했습니다.")
    image_pil = Image.open(BytesIO(file_bytes)).convert("RGB")
    return image_cv, image_pil

def reset_analysis_state_preserve_image():
    st.session_state.axis_y = 200
    st.session_state.y_max_pixel = 50
    st.session_state.baseline_y = 200
    st.session_state.y_max = 100.0
    st.session_state.y_min = 0.0
    st.session_state.plot_type = "Unknown"
    st.session_state.figure_name = ""
    st.session_state.x_labels_input = ""
    st.session_state.df_extracted = pd.DataFrame(
        columns=["selected", "figure_name", "X_Label", "Value", "Type", "x_pixel", "y_pixel"]
    )
    st.session_state.last_click_x = None
    st.session_state.last_click_y = None
    st.session_state.last_click_signature = None
    st.session_state.last_applied_click_signature = None
    st.session_state.input_axis_y = 200
    st.session_state.input_y_max_pixel = 50
    st.session_state.input_baseline_y = 200
    st.session_state.cursor_y = None
    st.session_state.cursor_step = 1
    st.session_state.selected_row_idx_memory = None

# =========================
# 자동 축 감지 (X, Y)
# =========================
def auto_detect_y_limits(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary_inv = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    h, w = image.shape[:2]

    kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, int(h * 0.3))))
    vert_lines = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel_v)
    col_counts = np.sum(vert_lines, axis=0)
    y_axis_x = int(np.argmax(col_counts)) if np.any(col_counts > 0) else int(w * 0.1)

    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, int(w * 0.2)), 1))
    horiz_lines = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel_h)
    row_counts = np.sum(horiz_lines, axis=1)
    y_indices = np.where(row_counts > 0)[0]
    axis_y_0 = int(max(y_indices)) if len(y_indices) > 0 else int(h * 0.9)

    start_y = int(h * 0.05)
    left = max(0, y_axis_x - 15)
    right = max(left + 1, y_axis_x)
    tick_roi_y = binary_inv[start_y:axis_y_0, left:right]
    row_counts_roi_y = np.sum(tick_roi_y, axis=1)
    tick_indices = np.where(row_counts_roi_y > (2 * 255))[0]

    axis_y_max = int(min(tick_indices)) + start_y if len(tick_indices) > 0 else int(h * 0.1)
    return axis_y_0, axis_y_max, y_axis_x

def auto_detect_x_ticks(image, y_axis_x, baseline_y):
    """
    [Bar_Plot.py 로직 적용]
    X축 Baseline 바로 아래(1px ~ 10px) 영역을 스캔하여 튀어나온 눈금의 X 좌표를 반환합니다.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # 눈금이 확실히 보이도록 임계값 설정
    _, binary_inv = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
    h, w = image.shape[:2]
    
    # 💡 Baseline 아래 1~10px 구간만 잘라냄
    scan_top = baseline_y + 1
    scan_bottom = min(h, baseline_y + 10)
    
    # Y축(0점) 오른쪽 영역만 스캔
    roi = binary_inv[scan_top:scan_bottom, y_axis_x + 5:]
    col_counts = np.sum(roi, axis=0)
    
    # 눈금 후보: 세로 방향으로 픽셀이 50% 이상 채워진 열
    threshold = (scan_bottom - scan_top) * 255 * 0.5
    raw_ticks = [xi for xi, c in enumerate(col_counts) if c > threshold]
    
    refined_ticks_x = []
    if raw_ticks:
        temp_group = [raw_ticks[0]]
        for i in range(1, len(raw_ticks)):
            # 5px 이내의 인접한 픽셀은 하나의 눈금으로 간주
            if raw_ticks[i] - raw_ticks[i-1] <= 5:
                temp_group.append(raw_ticks[i])
            else:
                # 오프셋(y_axis_x + 5)을 더해 전체 좌표로 복원
                refined_ticks_x.append(y_axis_x + 5 + int(np.mean(temp_group)))
                temp_group = [raw_ticks[i]]
        # 마지막 그룹 추가
        refined_ticks_x.append(y_axis_x + 5 + int(np.mean(temp_group)))
            
    return refined_ticks_x

# =========================
# Gemini 분석 & 에이전트 루프
# =========================
def run_gemini_analysis(image_pil):
    if not API_AVAILABLE:
        return None, f"Gemini API 모듈 import 실패: {API_IMPORT_ERROR}"
    try:
        key_path = find_api_key_file("vertex-490605-8d0be916872a.json")
        client = get_vertexai_client(key_path)

        prompt = """
        Analyze this chart and return ONLY valid JSON.
        Required format:
        {
          "y_max": float,
          "y_min": float,
          "x_labels": ["label1", "label2", "..."],
          "plot_type": "bar_plot" or "point_plot"
        }
        Do not include markdown fences.
        """
        res = client.models.generate_content(model="gemini-3.1-pro-preview", contents=[prompt, image_pil])
        text = res.text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(text), None
    except Exception as e:
        return None, f"Gemini 분석 실패: {e}"

def autonomous_y_finder(image_cv, target_x, baseline_y, y_max_pixel, client, status_placeholder, max_iterations=4):
    """
    [3단계 하이브리드 에이전트]
    1. 초기 위치 추정 (Pro) -> 2. 빠른 미세 보정 루프 (Flash) -> 3. 최종 정밀 검증 (Pro)
    """
    
    # ==========================================
    # 1단계: 초기 Y 좌표 추정 (Gemini Pro)
    # ==========================================
    status_placeholder.text(f"🧠 [X:{target_x}] 1단계: Pro 모델이 이미지 전체를 분석하여 초기 Y를 추정 중...")
    
    # 모델이 집중할 수 있도록 X 좌표 위치에 연한 노란색 수직 가이드라인을 그립니다.
    img_p1 = image_cv.copy()
    cv2.line(img_p1, (target_x, baseline_y), (target_x, max(0, y_max_pixel - 30)), (0, 255, 255), 2)
    pil_p1 = Image.fromarray(cv2.cvtColor(img_p1, cv2.COLOR_BGR2RGB))
    
    prompt_p1 = f"""
    Analyze this bar chart and return ONLY valid JSON.
    - The baseline (Y=0 equivalent) is at Y={baseline_y} pixels.
    - The maximum Y-axis tick is at Y={y_max_pixel} pixels.
    - I have drawn a YELLOW VERTICAL LINE at X={target_x} indicating the target bar.
    Estimate the exact Y-pixel coordinate of the top flat edge of the bar intersecting this yellow line.
    Required format: {{"estimated_y": int}}
    """
    
    try:
        res1 = client.models.generate_content(model="gemini-3.1-pro-preview", contents=[prompt_p1, pil_p1])
        data1 = json.loads(res1.text.strip().replace("```json", "").replace("```", "").strip())
        current_y = int(data1.get("estimated_y", baseline_y * 0.8)) # 실패 시 백업용 80% 지점
    except Exception as e:
        current_y = int(baseline_y * 0.8)

    # ==========================================
    # 2단계: 미세 조정 루프 (Gemini Flash)
    # ==========================================
    for i in range(max_iterations):
        status_placeholder.text(f"⚡ [X:{target_x}] 2단계: Flash 에이전트가 빠르게 좌표를 보정 중... ({i+1}회, Y={current_y})")
        
        img_p2 = image_cv.copy()
        cv2.line(img_p2, (target_x - 20, current_y), (target_x + 20, current_y), (0, 0, 255), 2)
        pil_p2 = Image.fromarray(cv2.cvtColor(img_p2, cv2.COLOR_BGR2RGB))
        
        prompt_p2 = """
        Analyze this chart and return ONLY valid JSON.
        당신은 빠른 시각 보정 에이전트입니다. 빨간색 가로선이 막대의 '최상단 평면'에 일치하는지 평가하세요.
        이미지 좌표계는 맨 위가 0, 아래로 갈수록 커집니다.
        {
          "status": "PERFECT" or "ADJUST",
          "move_pixels": int
        }
        - 완벽히 일치하면: {"status": "PERFECT", "move_pixels": 0}
        - 선을 위로 올려야 하면: {"status": "ADJUST", "move_pixels": -3}
        - 선을 아래로 내려야 하면: {"status": "ADJUST", "move_pixels": 3}
        """
        try:
            # 💡 빠르고 저렴한 Flash 모델 사용
            res2 = client.models.generate_content(model="gemini-2.5-flash", contents=[prompt_p2, pil_p2])
            data2 = json.loads(res2.text.strip().replace("```json", "").replace("```", "").strip())
            
            status = data2.get("status", "ADJUST")
            move_pixels = data2.get("move_pixels", 0)

            if status == "PERFECT" or move_pixels == 0:
                break
            else:
                current_y += move_pixels
                current_y = max(0, min(current_y, image_cv.shape[0] - 1))
        except Exception as e:
            break
            
    # ==========================================
    # 3단계: 최종 정밀 검증 (Gemini Pro)
    # ==========================================
    status_placeholder.text(f"🔬 [X:{target_x}] 3단계: Pro 모델이 오차 없이 최종 좌표(Y={current_y})를 검증 중...")
    
    img_p3 = image_cv.copy()
    cv2.line(img_p3, (target_x - 20, current_y), (target_x + 20, current_y), (0, 0, 255), 2)
    pil_p3 = Image.fromarray(cv2.cvtColor(img_p3, cv2.COLOR_BGR2RGB))
    
    prompt_p3 = """
    Analyze this chart and return ONLY valid JSON.
    당신은 정밀 검증 에이전트입니다. 빨간색 가로선이 막대의 '최상단 평면'에 1~2픽셀의 오차도 없이 완벽하게 일치하는지 최종 확인하세요.
    {
      "status": "PERFECT" or "ADJUST",
      "move_pixels": int
    }
    - 완벽하게 일치하면: {"status": "PERFECT", "move_pixels": 0}
    - 1~2픽셀의 미세 조정이 필요하면: {"status": "ADJUST", "move_pixels": 조정할픽셀수}
    """
    try:
        # 💡 가장 똑똑한 Pro 모델로 마지막 확인
        res3 = client.models.generate_content(model="gemini-3.1-pro-preview", contents=[prompt_p3, pil_p3])
        data3 = json.loads(res3.text.strip().replace("```json", "").replace("```", "").strip())
        
        final_move = data3.get("move_pixels", 0)
        current_y += final_move
        current_y = max(0, min(current_y, image_cv.shape[0] - 1))
    except Exception as e:
        pass

    status_placeholder.text(f"✅ [X:{target_x}] 추출 완료! (최종 Y={current_y})")
    return current_y

# =========================
# 값 계산
# =========================
def calculate_value_from_click(clicked_y: int):
    pixel_range = abs(st.session_state.axis_y - st.session_state.y_max_pixel)
    if pixel_range <= 0:
        raise ValueError("axis_y 와 y_max_pixel 이 같아서 값을 계산할 수 없습니다.")
    unit_per_pixel = (st.session_state.y_max - st.session_state.y_min) / pixel_range
    dist_from_baseline = st.session_state.baseline_y - clicked_y
    val = st.session_state.y_min + (dist_from_baseline * unit_per_pixel)
    return round(val, 4)

def ensure_cursor_y():
    if st.session_state.cursor_y is None:
        st.session_state.cursor_y = int(st.session_state.baseline_y)

def set_cursor_from_click(clicked_y: int):
    if st.session_state.image_cv is None: return
    st.session_state.cursor_y = max(0, min(st.session_state.image_cv.shape[0] - 1, int(clicked_y)))

def move_cursor(dy: int):
    ensure_cursor_y()
    new_y = int(st.session_state.cursor_y) + int(dy)
    st.session_state.cursor_y = max(0, min(st.session_state.image_cv.shape[0] - 1, new_y))

def apply_cursor_to_selected_row(selected_row_idx: int):
    ensure_cursor_y()
    if selected_row_idx is None or not (0 <= selected_row_idx < len(st.session_state.df_extracted)):
        return False, "유효한 행을 선택하세요."
    clicked_x = st.session_state.last_click_x if st.session_state.last_click_x is not None else 0
    clicked_y = int(st.session_state.cursor_y)
    value = calculate_value_from_click(clicked_y)
    st.session_state.df_extracted.at[selected_row_idx, "Value"] = value
    st.session_state.df_extracted.at[selected_row_idx, "x_pixel"] = int(clicked_x)
    st.session_state.df_extracted.at[selected_row_idx, "y_pixel"] = int(clicked_y)
    return True, value

def apply_click_to_selected_row(selected_row_idx: int, clicked_x: int, clicked_y: int):
    if selected_row_idx is None or not (0 <= selected_row_idx < len(st.session_state.df_extracted)):
        return False, "유효한 행을 선택하세요."
    value = calculate_value_from_click(clicked_y)
    st.session_state.df_extracted.at[selected_row_idx, "Value"] = value
    st.session_state.df_extracted.at[selected_row_idx, "x_pixel"] = int(clicked_x)
    st.session_state.df_extracted.at[selected_row_idx, "y_pixel"] = int(clicked_y)
    return True, value

# =========================
# 표시용 이미지 생성
# =========================
def build_display_image(selected_row_idx=None):
    if st.session_state.image_cv is None: return None
    display_img = st.session_state.image_cv.copy()
    h, w = display_img.shape[:2]

    axis_y = max(0, min(h - 1, int(st.session_state.axis_y)))
    y_max_pixel = max(0, min(h - 1, int(st.session_state.y_max_pixel)))
    baseline_y = max(0, min(h - 1, int(st.session_state.baseline_y)))

    cv2.line(display_img, (0, axis_y), (w, axis_y), (0, 0, 255), 2)
    cv2.line(display_img, (0, y_max_pixel), (w, y_max_pixel), (255, 0, 0), 2)
    cv2.line(display_img, (0, baseline_y), (w, baseline_y), (255, 0, 255), 2)

    ensure_cursor_y()
    cursor_y = max(0, min(h - 1, int(st.session_state.cursor_y)))
    overlay = display_img.copy()
    cv2.line(overlay, (0, cursor_y), (w, cursor_y), (0, 255, 255), 2)
    display_img = cv2.addWeighted(overlay, 0.35, display_img, 0.65, 0)
    cv2.rectangle(display_img, (0, max(0, cursor_y - 4)), (18, min(h - 1, cursor_y + 4)), (0, 255, 255), -1)

    for idx, row in st.session_state.df_extracted.iterrows():
        if pd.notna(row.get("x_pixel")) and pd.notna(row.get("y_pixel")):
            px_x, px_y = int(row["x_pixel"]), int(row["y_pixel"])
            px_x, px_y = max(0, min(w - 1, px_x)), max(0, min(h - 1, px_y))
            color, radius, alpha = ((0, 255, 255), 4, 0.40) if idx == selected_row_idx else ((0, 255, 0), 2, 0.22)
            overlay = display_img.copy()
            cv2.circle(overlay, (px_x, px_y), radius, color, -1)
            display_img = cv2.addWeighted(overlay, alpha, display_img, 1 - alpha, 0)

    return cv2.cvtColor(display_img, cv2.COLOR_BGR2RGB)

# =========================
# 업로드 처리
# =========================
def handle_upload(uploaded_file):
    if uploaded_file is None:
        # 파일이 없으면 세션 데이터 삭제 (선택 사항)
        st.session_state.image_cv = None
        return

    # 파일 바이트 추출
    file_bytes = uploaded_file.getvalue()
    file_hash = file_to_hash(file_bytes)

    # 새로운 파일인 경우에만 로드 (하지만 image_cv가 None이면 무조건 로드)
    if st.session_state.uploaded_file_hash != file_hash or st.session_state.image_cv is None:
        try:
            image_cv, image_pil = load_image_from_bytes(file_bytes)
            
            # 세션 상태 업데이트
            st.session_state.image_cv = image_cv
            st.session_state.image_pil = image_pil
            st.session_state.uploaded_file_hash = file_hash
            st.session_state.uploaded_file_name = uploaded_file.name
            
            # 초기화 (이미지는 유지하면서 분석 값만 리셋)
            reset_analysis_state_preserve_image()
            st.session_state.cursor_y = int(st.session_state.baseline_y)
            
            # 중요: 강제 리런을 통해 메인 화면의 if 문이 image_cv를 인식하게 함
            st.rerun() 
        except Exception as e:
            st.error(f"이미지 로딩 중 오류: {e}")

# =========================
# UI
# =========================
st.title("📊 LNPDB Plot Extractor (with Autonomous Agent)")

with st.sidebar:
    st.header("1. 이미지 업로드")
    uploaded_file = st.file_uploader("이미지 업로드", type=["png", "jpg", "jpeg"])
    handle_upload(uploaded_file)

    if st.session_state.image_cv is not None:
        col_table, col_img = st.columns([0.9, 1.8], gap="large")
        \
        # 버튼 1: 기존 자동 분석 (축 감지 + 라벨 파싱)
        if st.button("🤖 1차 자동 분석 (라벨 및 축 감지)", use_container_width=True):
            with st.spinner("축과 라벨을 분석 중..."):
                try:
                    detected_y0, detected_ymax_px, _ = auto_detect_y_limits(st.session_state.image_cv)
                    st.session_state.axis_y = int(detected_y0)
                    st.session_state.baseline_y = int(detected_y0)
                    st.session_state.y_max_pixel = int(detected_ymax_px)
                    st.session_state.input_axis_y = int(detected_y0)
                    st.session_state.input_baseline_y = int(detected_y0)
                    st.session_state.input_y_max_pixel = int(detected_ymax_px)

                    data, err = run_gemini_analysis(st.session_state.image_pil)
                    if err:
                        st.warning(err)
                    elif data:
                        st.session_state.y_max = float(data.get("y_max", 100.0))
                        st.session_state.y_min = float(data.get("y_min", 0.0))
                        st.session_state.plot_type = str(data.get("plot_type", "Unknown"))
                        labels = [str(x).strip() for x in data.get("x_labels", []) if str(x).strip()]

                        st.session_state.df_extracted = pd.DataFrame({
                            "selected": [False] * len(labels),
                            "figure_name": [st.session_state.figure_name] * len(labels),
                            "X_Label": labels,
                            "Value": [None] * len(labels),
                            "Type": [st.session_state.plot_type] * len(labels),
                            "x_pixel": [None] * len(labels),
                            "y_pixel": [None] * len(labels),
                        })
                        st.session_state.x_labels_input = ", ".join(labels)
                        st.success("1차 자동 분석 완료")
                except Exception as e:
                    st.error(f"분석 중 오류 발생: {e}")

        # 버튼 2: 에이전트 자율 루프 (핵심 신규 기능)
        st.markdown("---")
        if st.button("🚀 2차 정밀 자율 추출 (에이전트 구동)", type="primary", use_container_width=True):
            if not API_AVAILABLE:
                st.error("API 연동 에러로 에이전트를 구동할 수 없습니다.")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                try:
                    # 1. 축의 X, Y 좌표 감지
                    y0, _, y_axis_x = auto_detect_y_limits(st.session_state.image_cv)
                    # 2. X 눈금(막대 중심) 모두 감지
                    x_centers = auto_detect_x_ticks(st.session_state.image_cv, y_axis_x, st.session_state.baseline_y)
                    
                    if not x_centers:
                        st.warning("X축 눈금(막대)을 감지하지 못했습니다.")
                    else:
                        st.success(f"총 {len(x_centers)}개의 데이터를 감지했습니다. 에이전트를 시작합니다.")
                        
                        key_path = find_api_key_file("vertex-490605-8d0be916872a.json")
                        client = get_vertexai_client(key_path)
                        
                        # 표 길이를 X 눈금 수에 맞춤
                        df = st.session_state.df_extracted
                        if len(df) != len(x_centers):
                            # 기존 라벨 유지하되 모자라면 채우기
                            labels = df["X_Label"].tolist()
                            while len(labels) < len(x_centers):
                                labels.append(f"Bar {len(labels)+1}")
                            df = pd.DataFrame({
                                "selected": [False] * len(x_centers),
                                "figure_name": [st.session_state.figure_name] * len(x_centers),
                                "X_Label": labels[:len(x_centers)],
                                "Value": [None] * len(x_centers),
                                "Type": [st.session_state.plot_type] * len(x_centers),
                                "x_pixel": [None] * len(x_centers),
                                "y_pixel": [None] * len(x_centers),
                            })
                            st.session_state.df_extracted = df

                        # 3. 각 X 눈금마다 에이전트 루프 실행
                        for idx, target_x in enumerate(x_centers):
                            initial_y = int(st.session_state.baseline_y * 0.8) # 대략 80% 높이에서 추정 시작
                            
                            # 에이전트가 완벽한 Y좌표를 찾음
                            final_y = autonomous_y_finder(
                                st.session_state.image_cv, 
                                target_x, 
                                initial_y, 
                                st.session_state.y_max_pixel,  
                                client, 
                                status_text
                            )
                            
                            # 값 계산 및 표 반영
                            value = calculate_value_from_click(final_y)
                            st.session_state.df_extracted.at[idx, "Value"] = value
                            st.session_state.df_extracted.at[idx, "x_pixel"] = target_x
                            st.session_state.df_extracted.at[idx, "y_pixel"] = final_y
                            
                            progress_bar.progress((idx + 1) / len(x_centers))
                        
                        status_text.success("🎉 에이전트가 모든 데이터의 정밀 추출을 완료했습니다!")
                        st.rerun()

                except Exception as e:
                    st.error(f"에이전트 실행 중 오류 발생: {e}")
    else:
        st.info("👈 왼쪽 사이드바에서 이미지 파일을 업로드해 주세요.")
        st.image("https://via.placeholder.com/800x400.png?text=Waiting+for+Upload", use_column_width=True)

    st.divider()
    st.header("2. 수동 설정")
    st.session_state.axis_y = st.number_input("기준 X축(0점) 높이(px)", min_value=0, value=int(st.session_state.input_axis_y), step=1)
    st.session_state.y_max_pixel = st.number_input("Y Max 눈금 높이(px)", min_value=0, value=int(st.session_state.input_y_max_pixel), step=1)
    st.session_state.baseline_y = st.number_input("측정 시작점 높이(px)", min_value=0, value=int(st.session_state.input_baseline_y), step=1)
    st.session_state.y_max = st.number_input("Y Max", value=float(st.session_state.y_max), step=0.1)
    st.session_state.y_min = st.number_input("Y Min", value=float(st.session_state.y_min), step=0.1)
    
    st.session_state.figure_name = st.text_input("Figure name", value=st.session_state.figure_name, placeholder="예: Figure 2B")

    st.header("3. 라벨 수동 입력/수정")
    x_labels_text = st.text_area("X labels (콤마로 구분)", value=st.session_state.x_labels_input, height=120)
    if st.button("라벨 표 생성/갱신", use_container_width=True):
        labels = [x.strip() for x in x_labels_text.split(",") if x.strip()]
        st.session_state.x_labels_input = ", ".join(labels)
        st.session_state.df_extracted = pd.DataFrame({
            "selected": [False] * len(labels), "figure_name": [st.session_state.figure_name] * len(labels),
            "X_Label": labels, "Value": [None] * len(labels), "Type": [st.session_state.plot_type] * len(labels),
            "x_pixel": [None] * len(labels), "y_pixel": [None] * len(labels)
        })
        st.success("표를 갱신했습니다.")

# =========================
# 메인 화면
# =========================
if st.session_state.image_cv is not None:
    col_table, col_img = st.columns([0.9, 1.8], gap="large")

    with col_table:
        st.subheader("5. 데이터 매칭 표")
        required_cols = ["selected", "figure_name", "X_Label", "Value", "Type", "x_pixel", "y_pixel"]
        if "df_extracted" not in st.session_state or st.session_state.df_extracted is None:
            st.session_state.df_extracted = pd.DataFrame(columns=required_cols)
        for col in required_cols:
            if col not in st.session_state.df_extracted.columns:
                st.session_state.df_extracted[col] = False if col == "selected" else None

        st.session_state.df_extracted = st.session_state.df_extracted[required_cols].reset_index(drop=True)

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("행 추가", use_container_width=True):
                new_row = {"selected": False, "figure_name": st.session_state.figure_name, "X_Label": None, "Value": None, "Type": st.session_state.plot_type, "x_pixel": None, "y_pixel": None}
                st.session_state.df_extracted = pd.concat([st.session_state.df_extracted, pd.DataFrame([new_row])], ignore_index=True)
                st.rerun()
        with btn_col2:
            if st.button("선택 행 삭제", use_container_width=True):
                st.session_state.df_extracted = st.session_state.df_extracted[st.session_state.df_extracted["selected"] != True].reset_index(drop=True)
                st.rerun()

        edited_df = st.data_editor(
            st.session_state.df_extracted, use_container_width=True, hide_index=True, num_rows="fixed",
            column_config={
                "selected": st.column_config.CheckboxColumn("선택", default=False),
                "Value": st.column_config.NumberColumn("Value", format="%.4f"),
                "x_pixel": st.column_config.NumberColumn("x_pixel", disabled=True),
                "y_pixel": st.column_config.NumberColumn("y_pixel", disabled=True),
            }, disabled=["x_pixel", "y_pixel"], key="df_editor_main",
        )
        st.session_state.df_extracted = edited_df.copy().reset_index(drop=True)

        selected_indices = st.session_state.df_extracted.index[st.session_state.df_extracted["selected"] == True].tolist()
        selected_row_idx = selected_indices[0] if len(selected_indices) > 0 else None
        
        # CSV 다운로드 추가
        st.divider()
        csv_data = st.session_state.df_extracted.to_csv(index=False).encode('utf-8')
        st.download_button("📥 현재 표를 CSV로 저장", data=csv_data, file_name=f"LNPDB_{st.session_state.figure_name or 'extracted'}.csv", mime="text/csv", use_container_width=True)

    with col_img:
        st.subheader("6. 그래프 미리보기 (클릭하여 수동 보정 가능)")
        img_rgb = build_display_image(selected_row_idx)

        if img_rgb is not None:
            display_width = min(img_rgb.shape[1] * 2, 1800)
            try:
                clicked = streamlit_image_coordinates(Image.fromarray(img_rgb), key="lnp_image_click", width=display_width)

                if clicked is not None:
                    scale_x = img_rgb.shape[1] / display_width
                    clicked_x = int(round(clicked["x"] * scale_x))
                    clicked_y = int(round(clicked["y"] * scale_x))
                    click_signature = f"{clicked_x}_{clicked_y}"

                    if st.session_state.last_click_signature != click_signature:
                        st.session_state.last_click_x = max(0, min(img_rgb.shape[1] - 1, clicked_x))
                        st.session_state.last_click_y = max(0, min(img_rgb.shape[0] - 1, clicked_y))
                        st.session_state.last_click_signature = click_signature
                        set_cursor_from_click(st.session_state.last_click_y)
                        st.rerun()

                ensure_cursor_y()
                c1, c2, c3, c4 = st.columns([1, 1, 2, 2])
                with c1:
                    if st.button("▲ 위", use_container_width=True):
                        move_cursor(-int(st.session_state.cursor_step))
                        st.rerun()
                with c2:
                    if st.button("▼ 아래", use_container_width=True):
                        move_cursor(int(st.session_state.cursor_step))
                        st.rerun()
                with c3: st.number_input("이동 px", min_value=1, step=1, key="cursor_step")
                with c4: st.number_input("현재 bar y", min_value=0, step=1, key="cursor_y")

                if selected_row_idx is not None:
                    if st.button("수동 조작한 현재 값 적용", use_container_width=True):
                        ok, result = apply_cursor_to_selected_row(selected_row_idx)
                        if ok:
                            st.success(f"반영 완료: Value={result}")
                            st.rerun()
                        else:
                            st.warning(result)
            except Exception as e:
                st.image(img_rgb, use_container_width=True, caption="수동 보정용 이미지 (클릭 기능 미작동)")

if __name__ == "__main__":
    import sys
    from streamlit.web import cli
    from streamlit import runtime

    if not runtime.exists():
        sys.argv = ["streamlit", "run", __file__]
        sys.exit(cli.main())

# python -m streamlit run 경로/value_extractor_image_coordinates.py