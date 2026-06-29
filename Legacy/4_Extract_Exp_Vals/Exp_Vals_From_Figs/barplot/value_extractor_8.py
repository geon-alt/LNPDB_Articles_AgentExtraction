import streamlit as st
import cv2
import numpy as np
import pandas as pd
from PIL import Image
import json
import hashlib
import re
from io import BytesIO
from streamlit_image_coordinates import streamlit_image_coordinates
from streamlit_drawable_canvas import st_canvas
import sys, os
import traceback
from pathlib import Path

try:
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode
    AGGRID_AVAILABLE = True
    print("✅ st_aggrid 모듈이 성공적으로 로드되었습니다.")
except Exception:
    AgGrid = None
    GridOptionsBuilder = None
    GridUpdateMode = None
    DataReturnMode = None
    AGGRID_AVAILABLE = False

# =========================
# Gemini API 설정
# =========================
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ID = "avian-light-492007-c2"
PROJECT_ROOT = None
for p in [CURRENT_DIR, *CURRENT_DIR.parents]:
    if (p / "find_api.py").exists():
        PROJECT_ROOT = p
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
        break

API_IMPORT_ERROR = None

try:
    from find_api import get_genai_client, find_api_key_file
    API_AVAILABLE = True
except Exception as e:
    API_AVAILABLE = False
    API_IMPORT_ERROR = str(e)

# =========================
# Streamlit 기본 설정
# =========================
st.set_page_config(layout="wide", page_title="LNPDB Plot Extractor")

DEBUG_DISABLE_AGGRID = os.environ.get("LNPDB_DISABLE_AGGRID", "1").strip() == "0"
DEBUG_DISABLE_CANVAS = os.environ.get("LNPDB_DISABLE_CANVAS", "1").strip() == "0"
DEBUG_DISABLE_IMAGE_COORDS = os.environ.get("LNPDB_DISABLE_IMAGE_COORDS", "1").strip() == "0"

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
        "groups_input": "", # 💡 다중 색상/그룹 입력용
        "orientation": "Vertical (세로형)", # 💡 가로/세로 방향
        "is_log_scale": False, # 💡 로그 스케일 여부
        "zoom_region": None, # 💡 [신규] 드래그로 선택한 돋보기 영역 좌표 저장용
        "image_zoom": 100, # 💡 이미지 줌 비율
        "df_calibration": pd.DataFrame({ 
            "selected": [False, False], # 💡 선택 체크박스 추가
            "Pixel": [200, 50],
            "Value": [0.0, 100.0]
        }),
        "df_extracted": pd.DataFrame(
            # 💡 'Group' 컬럼 추가
            columns=["selected", "figure_name", "X_Label", "Group", "Value", "Type", "x_pixel", "y_pixel"]
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
        "selected_calib_idx_memory": None,
        "aggrid_runtime_disabled": False,
        "aggrid_runtime_error": None,
        "pending_clicks": [],
        "pending_click_message": None,
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
        columns=["selected", "figure_name", "X_Label", "Group", "Value", "Type", "x_pixel", "y_pixel"]
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
    st.session_state.selected_calib_idx_memory = None
    st.session_state.aggrid_runtime_disabled = False
    st.session_state.aggrid_runtime_error = None
    st.session_state.pending_clicks = []
    st.session_state.pending_click_message = None

# =========================
# 자동 축 감지 (X, Y)
# =========================
def auto_detect_y_limits(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # 💡 [해결1] 임계값을 200으로 올려 희미한 눈금도 까맣게 잡히도록 상향
    _, binary_inv = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    h, w = image.shape[:2]

    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, int(w * 0.2)), 1))
    horiz_lines = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel_h)
    row_counts_h = np.sum(horiz_lines, axis=1)
    y_indices = np.where(row_counts_h > 0)[0]
    axis_y_0 = int(max(y_indices)) if len(y_indices) > 0 else int(h * 0.9)
    
    x_line_pixels = np.where(horiz_lines[axis_y_0, :] > 0)[0]
    x_start_px = x_line_pixels[0] if len(x_line_pixels) > 0 else int(w * 0.1)

    kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, int(h * 0.1))))
    vert_lines = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel_v)
    col_counts_v = np.sum(vert_lines, axis=0)
    
    search_range = col_counts_v[max(0, x_start_px - 30) : min(w, x_start_px + 30)]
    if np.any(search_range > 0):
        y_axis_x = max(0, x_start_px - 30) + int(np.argmax(search_range))
    else:
        y_axis_x = x_start_px

    axis_top_y = 0
    
    # 💡 [해결2] 기존 필터 삭제 -> Y축 기둥 '바로 왼쪽(6픽셀)' 허공을 스캔하여 튀어나온 픽셀 감지
    roi_left = binary_inv[axis_top_y:axis_y_0, max(0, y_axis_x - 6) : y_axis_x]
    row_counts = np.sum(roi_left, axis=1)
    
    tick_rows_relative = np.where(row_counts > 0)[0]
    tick_indices = tick_rows_relative + axis_top_y

    axis_y_max = int(min(tick_indices)) if len(tick_indices) > 0 else int(h * 0.1)
    return axis_y_0, axis_y_max, y_axis_x

def auto_detect_all_y_ticks(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # 💡 [해결1] 150 -> 200 상향
    _, binary_inv = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    h, w = image.shape[:2]

    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, int(w * 0.2)), 1))
    horiz_lines = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel_h)
    row_counts_h = np.sum(horiz_lines, axis=1)
    y_indices = np.where(row_counts_h > 0)[0]
    axis_y_0 = int(max(y_indices)) if len(y_indices) > 0 else int(h * 0.9)
    
    x_line_pixels = np.where(horiz_lines[axis_y_0, :] > 0)[0]
    x_start_px = x_line_pixels[0] if len(x_line_pixels) > 0 else int(w * 0.1)

    kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, int(h * 0.1))))
    vert_lines = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel_v)
    col_counts_v = np.sum(vert_lines, axis=0)
    
    search_range = col_counts_v[max(0, x_start_px - 30) : min(w, x_start_px + 30)]
    if np.any(search_range > 0):
        y_axis_x = max(0, x_start_px - 30) + int(np.argmax(search_range))
    else:
        y_axis_x = x_start_px

    axis_top_y = 0 
    scan_bottom = axis_y_0 
    
    # 💡 [해결2] Y축 기둥 바로 왼쪽(6픽셀 너비)만 도려내어 검사 (수직선 간섭 100% 제거)
    roi_left = binary_inv[axis_top_y:scan_bottom, max(0, y_axis_x - 6) : y_axis_x]
    row_counts = np.sum(roi_left, axis=1)
    
    # 1픽셀이라도 검은색이 튀어나와 있으면 눈금으로 즉시 인정
    tick_rows_relative = np.where(row_counts > 0)[0] 
    tick_rows = tick_rows_relative + axis_top_y

    detected_y_pixels = []
    if len(tick_rows) > 0:
        temp_group = [tick_rows[0]]
        for i in range(1, len(tick_rows)):
            if tick_rows[i] - tick_rows[i-1] <= 5: 
                temp_group.append(tick_rows[i])
            else:
                detected_y_pixels.append(int(np.mean(temp_group)))
                temp_group = [tick_rows[i]]
        detected_y_pixels.append(int(np.mean(temp_group)))

    return sorted(detected_y_pixels, reverse=True), y_axis_x

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

def auto_detect_all_x_val_ticks(image):
    """💡 [신규] 가로형 그래프를 위한 X축(수평) 물리 눈금 감지기"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary_inv = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    h, w = image.shape[:2]

    # X축(가장 긴 가로선) 찾기
    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, int(w * 0.2)), 1))
    horiz_lines = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel_h)
    row_counts_h = np.sum(horiz_lines, axis=1)
    y_indices = np.where(row_counts_h > 0)[0]
    axis_y_0 = int(max(y_indices)) if len(y_indices) > 0 else int(h * 0.9)

    x_line_pixels = np.where(horiz_lines[axis_y_0, :] > 0)[0]
    x_start_px = x_line_pixels[0] if len(x_line_pixels) > 0 else int(w * 0.1)

    # 💡 [초고감도] X축 선 바로 아래 6픽셀 허공을 스캔하여 튀어나온 픽셀 감지
    scan_top = axis_y_0
    scan_bottom = min(h, axis_y_0 + 6)
    
    roi_bottom = binary_inv[scan_top:scan_bottom, x_start_px:]
    col_counts = np.sum(roi_bottom, axis=0)
    
    # 1픽셀이라도 튀어나와 있으면 눈금으로 인정
    tick_cols_relative = np.where(col_counts > 0)[0] 
    tick_cols = tick_cols_relative + x_start_px

    detected_x_pixels = []
    if len(tick_cols) > 0:
        temp_group = [tick_cols[0]]
        for i in range(1, len(tick_cols)):
            if tick_cols[i] - tick_cols[i-1] <= 5: 
                temp_group.append(tick_cols[i])
            else:
                detected_x_pixels.append(int(np.mean(temp_group)))
                temp_group = [tick_cols[i]]
        detected_x_pixels.append(int(np.mean(temp_group)))

    return sorted(detected_x_pixels), axis_y_0

# =========================
# Gemini 분석 & 에이전트 루프
# =========================
API_MODE = os.environ.get("GEMINI_API_MODE", "vertex").strip().lower()
# GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()


def extract_text_from_genai_response(response) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if content is None:
            continue

        parts = getattr(content, "parts", None) or []
        collected = []

        for part in parts:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text.strip():
                collected.append(part_text)

        if collected:
            return "\n".join(collected).strip()

    raise ValueError("Gemini 응답에서 text를 추출하지 못했습니다.")


def parse_json_from_response_text(text: str):
    cleaned = text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)


# =========================
# Helper functions for axis value parsing
# =========================
def normalize_superscript_text(text: str) -> str:
    superscript_map = str.maketrans({
        '⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4',
        '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9',
        '⁺': '+', '⁻': '-', '⁽': '(', '⁾': ')'
    })
    return text.translate(superscript_map)


def parse_axis_value_label(raw_value):
    """
    Gemini가 축 라벨을 다음처럼 반환해도 숫자로 안전하게 변환합니다.
    예:
    - 100
    - "10^9"
    - "×10^9"
    - "x10^9"
    - "1×10^9"
    - "10⁹"
    - "×10⁹"
    - "1e9"
    """
    if raw_value is None:
        return None

    if isinstance(raw_value, (int, float, np.integer, np.floating)):
        return float(raw_value)

    s = str(raw_value).strip()
    if not s:
        return None

    s = normalize_superscript_text(s)
    s = s.replace(',', '').replace(' ', '')
    s = s.replace('−', '-')
    s = s.replace('×', 'x').replace('*', 'x')

    # 괄호나 불필요한 문자 제거 전, 자주 나오는 패턴 우선 처리
    # 1) 순수 숫자 / 소수 / 음수 / 지수표기
    try:
        return float(s)
    except Exception:
        pass

    # 2) 10^9, 10**9
    m = re.fullmatch(r'10(?:\^|\*\*)([-+]?\d+(?:\.\d+)?)', s, flags=re.IGNORECASE)
    if m:
        return 10.0 ** float(m.group(1))

    # 3) x10^9, ×10^9, 1x10^9, 2.5x10^3, x10**9
    m = re.fullmatch(r'(?:([-+]?\d+(?:\.\d+)?)?)x?10(?:\^|\*\*)([-+]?\d+(?:\.\d+)?)', s, flags=re.IGNORECASE)
    if m:
        coeff = float(m.group(1)) if m.group(1) not in (None, '') else 1.0
        exp = float(m.group(2))
        return coeff * (10.0 ** exp)

    # 4) 10-9, x10-9 같은 OCR/Gemini 변형을 보정하지는 않고, 10^ 또는 10** 형태만 허용
    # 5) 문자열 내부에서 유효 숫자만 마지막으로 추출 시도
    numeric_match = re.search(r'[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?', s, flags=re.IGNORECASE)
    if numeric_match and numeric_match.group(0) == s:
        return float(numeric_match.group(0))

    return None

def run_gemini_analysis(image_pil, tick_count=None, orientation="Vertical (세로형)"):
    if not API_AVAILABLE:
        return None, f"Gemini API 모듈 import 실패: {API_IMPORT_ERROR}"

    try:
        api_path = find_api_key_file("vertex.json")  # API 키 파일 경로 찾기
        client = get_genai_client(mode="vertex", api_path=api_path, project=PROJECT_ID)

        # 💡 [핵심] 가로/세로 방향에 따라 제미니에게 내리는 지시사항이 완전히 뒤바뀜!
        is_horiz = "Horizontal" in orientation
        if is_horiz:
            val_desc = "X축(가로축) 하단 눈금 아래에 써진 수치값들 (왼쪽에서 오른쪽 방향 순서)"
            cat_desc = "Y축(세로축) 좌측에 적힌 항목명/카테고리 이름 리스트 (위에서 아래 방향 순서)"
            tick_ins = f"X축(가로축)을 따라 물리적으로 총 {tick_count}개의 눈금이 감지되었습니다." if tick_count else ""
        else:
            val_desc = "Y축(세로축) 좌측 눈금 옆에 써진 수치값들 (아래에서 위 방향 순서)"
            cat_desc = "X축(가로축) 하단에 적힌 항목명/카테고리 이름 리스트 (왼쪽에서 오른쪽 방향 순서)"
            tick_ins = f"Y축(세로축)을 따라 물리적으로 총 {tick_count}개의 눈금이 감지되었습니다." if tick_count else ""

        tick_instruction = ""
        if tick_count is not None:
            tick_instruction = f"""
            [중요 지시사항]
            OpenCV를 통해 {tick_ins}
            따라서 'value_labels' 배열의 원소 개수는 반드시 정확히 {tick_count}개여야 합니다.
            만약 축이 생략되어 빈 공간이 있다면 직전 값을 중복으로 채워서라도 배열 길이를 맞추세요.
            """

        prompt = f"""
        당신은 그래프 전문 분석가입니다. 이미지에서 다음 정보를 JSON으로 반환하세요:
        Required format:
        {{
          "value_labels": [1, 10, 100], // {val_desc}
          // 💡 [중요] 숫자가 10^0, 10^1 같은 지수 형태라면 1, 10, 100 처럼 계산하거나 "10^1" 형태로 넣으세요.
          {tick_instruction}
          "category_labels": ["label1", "label2", "..."], // {cat_desc}
          "group_labels": ["Control", "APOE KO"], // 범례(Legend)에 있는 그룹/색상 이름 (없으면 [])
          "plot_type": "bar_plot" or "point_plot"
        }}
        Do not include markdown fences.
        """
        res = client.models.generate_content(model="gemini-3.1-pro-preview", contents=[prompt, image_pil])
        text = res.text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(text), None
    except Exception as e:
        return None, f"Gemini 분석 실패: {e}"

def autonomous_y_finder(image_cv, target_x, baseline_y, y_max_pixel, client, status_placeholder, x_label="", group_name="", max_iterations=4):
    """
    [3단계 하이브리드 에이전트] - 기존 알고리즘 유지 + 라벨/그룹 정보 주입
    """
    # ==========================================
    # 1단계: 초기 Y 좌표 추정 (Gemini Pro)
    # ==========================================
    status_placeholder.text(f"🧠 [{x_label} - {group_name}] 1단계: Pro 모델 초기 Y 추정 중...")
    
    img_p1 = image_cv.copy()
    cv2.line(img_p1, (target_x, baseline_y), (target_x, max(0, y_max_pixel - 30)), (0, 255, 255), 2)
    pil_p1 = Image.fromarray(cv2.cvtColor(img_p1, cv2.COLOR_BGR2RGB))
    
    prompt_p1 = f"""
    Analyze this bar chart and return ONLY valid JSON.
    - The baseline (Y=0 equivalent) is at Y={baseline_y} pixels.
    - The maximum Y-axis tick is at Y={y_max_pixel} pixels.
    - I have drawn a YELLOW VERTICAL LINE at X={target_x} indicating the category '{x_label}'.
    - We are looking for the bar corresponding to the group/color: '{group_name}'.
    
    Estimate the exact Y-pixel coordinate of the top flat edge of the '{group_name}' bar near the yellow line.
    Required format: {{"estimated_y": int}}
    """
    
    try:
        res1 = client.models.generate_content(model="gemini-3.1-pro-preview", contents=[prompt_p1, pil_p1])
        data1 = json.loads(res1.text.strip().replace("```json", "").replace("```", "").strip())
        current_y = int(data1.get("estimated_y", baseline_y * 0.8))
    except Exception as e:
        current_y = int(baseline_y * 0.8)

    # ==========================================
    # 2단계: 미세 조정 루프 (Gemini Flash)
    # ==========================================
    for i in range(max_iterations):
        status_placeholder.text(f"⚡ [{x_label} - {group_name}] 2단계: Flash 에이전트 보정 중... ({i+1}회, Y={current_y})")
        
        img_p2 = image_cv.copy()
        cv2.line(img_p2, (target_x - 20, current_y), (target_x + 20, current_y), (0, 0, 255), 2)
        pil_p2 = Image.fromarray(cv2.cvtColor(img_p2, cv2.COLOR_BGR2RGB))
        
        prompt_p2 = f"""
        Analyze this chart and return ONLY valid JSON.
        당신은 빠른 시각 보정 에이전트입니다. 빨간색 가로선이 '{x_label}' 항목의 '{group_name}' 색상 막대 '최상단 평면'에 일치하는지 평가하세요.
        이미지 좌표계는 맨 위가 0, 아래로 갈수록 커집니다.
        {{
          "status": "PERFECT" or "ADJUST",
          "move_pixels": int
        }}
        - 완벽히 일치하면: {{"status": "PERFECT", "move_pixels": 0}}
        - 선을 위로 올려야 하면: {{"status": "ADJUST", "move_pixels": -3}}
        - 선을 아래로 내려야 하면: {{"status": "ADJUST", "move_pixels": 3}}
        """
        try:
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
    status_placeholder.text(f"🔬 [{x_label} - {group_name}] 3단계: Pro 모델 최종 검증 중...")
    
    img_p3 = image_cv.copy()
    cv2.line(img_p3, (target_x - 20, current_y), (target_x + 20, current_y), (0, 0, 255), 2)
    pil_p3 = Image.fromarray(cv2.cvtColor(img_p3, cv2.COLOR_BGR2RGB))
    
    prompt_p3 = f"""
    Analyze this chart and return ONLY valid JSON.
    당신은 정밀 검증 에이전트입니다. 빨간색 가로선이 '{group_name}' 막대의 '최상단 평면'에 완벽하게 일치하는지 최종 확인하세요.
    {{
      "status": "PERFECT" or "ADJUST",
      "move_pixels": int
    }}
    - 완벽하게 일치하면: {{"status": "PERFECT", "move_pixels": 0}}
    - 미세 조정이 필요하면: {{"status": "ADJUST", "move_pixels": 조정할픽셀수}}
    """
    try:
        res3 = client.models.generate_content(model="gemini-3.1-pro-preview", contents=[prompt_p3, pil_p3])
        data3 = json.loads(res3.text.strip().replace("```json", "").replace("```", "").strip())
        
        final_move = data3.get("move_pixels", 0)
        current_y += final_move
        current_y = max(0, min(current_y, image_cv.shape[0] - 1))
    except Exception as e:
        pass

    status_placeholder.text(f"✅ [{x_label} - {group_name}] 추출 완료! (최종 Y={current_y})")
    return current_y

# =========================
# 💡 값 계산 (다중 구간 보간 & 로그 스케일 지원)
# =========================
def calculate_custom_value(clicked_pixel: float):
    df_cal = st.session_state.df_calibration.dropna().sort_values('Value').reset_index(drop=True)
    if len(df_cal) < 2: return 0.0
    
    pixels = df_cal['Pixel'].values
    values = df_cal['Value'].values
    is_log = st.session_state.is_log_scale
    
    # 로그 변환 함수
    def to_space(v): return np.log10(v) if is_log and v > 0 else float(v)
    def from_space(v): return 10**v if is_log else float(v)

    val_space = np.array([to_space(v) for v in values])
    
    # 클릭한 픽셀과 가장 가까운 두 눈금을 찾아 해당 구간 내에서만 비율 계산 (잘린 축 해결)
    distances = np.abs(pixels - clicked_pixel)
    idx1, idx2 = np.argsort(distances)[:2]
    
    p1, p2 = pixels[idx1], pixels[idx2]
    v1, v2 = val_space[idx1], val_space[idx2]
    
    if p1 == p2: return from_space(v1)
    
    ratio = (clicked_pixel - p1) / (p2 - p1)
    calc_val_space = v1 + ratio * (v2 - v1)
    
    return round(from_space(calc_val_space), 4)

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
    
    # 💡 방향 확인
    is_horizontal = "Horizontal" in st.session_state.orientation
    
    # 💡 마지막 클릭 X와 현재 커서 Y 중 방향에 맞는 것 선택
    clicked_x = st.session_state.last_click_x if st.session_state.last_click_x is not None else 0
    clicked_y = int(st.session_state.cursor_y)
    
    target_pixel = clicked_x if is_horizontal else clicked_y
    
    # 💡 새로운 구간 보간 함수(calculate_custom_value) 사용
    value = calculate_custom_value(target_pixel)
    
    st.session_state.df_extracted.at[selected_row_idx, "Value"] = value
    st.session_state.df_extracted.at[selected_row_idx, "x_pixel"] = int(clicked_x)
    st.session_state.df_extracted.at[selected_row_idx, "y_pixel"] = int(clicked_y)
    return True, value


def apply_click_to_selected_row(selected_row_idx: int, clicked_x: int, clicked_y: int):
    if selected_row_idx is None or not (0 <= selected_row_idx < len(st.session_state.df_extracted)):
        return False, "유효한 행을 선택하세요."

    # 💡 축 방향(가로/세로)에 맞춰 기준 픽셀을 똑똑하게 선택하도록 수정
    is_horizontal = "Horizontal" in st.session_state.orientation
    target_pixel = clicked_x if is_horizontal else clicked_y

    value = calculate_custom_value(target_pixel)  # ✅ 새 함수명으로 변경

    st.session_state.df_extracted.at[selected_row_idx, "Value"] = value
    st.session_state.df_extracted.at[selected_row_idx, "x_pixel"] = int(clicked_x)
    st.session_state.df_extracted.at[selected_row_idx, "y_pixel"] = int(clicked_y)
    return True, value


# =========================
# Pending click helpers for batch-apply workflow
# =========================
def queue_click_for_selected_row(selected_row_idx: int, clicked_x: int, clicked_y: int):
    if selected_row_idx is None or not (0 <= selected_row_idx < len(st.session_state.df_extracted)):
        return False, "유효한 행을 선택하세요."

    is_horizontal = "Horizontal" in st.session_state.orientation
    target_pixel = clicked_x if is_horizontal else clicked_y
    value = calculate_custom_value(target_pixel)

    pending = list(st.session_state.get("pending_clicks", []))
    updated = False
    for item in pending:
        if int(item.get("row_idx", -1)) == int(selected_row_idx):
            item["x_pixel"] = int(clicked_x)
            item["y_pixel"] = int(clicked_y)
            item["value"] = value
            updated = True
            break

    if not updated:
        pending.append({
            "row_idx": int(selected_row_idx),
            "x_pixel": int(clicked_x),
            "y_pixel": int(clicked_y),
            "value": value,
        })

    st.session_state.pending_clicks = pending
    st.session_state.pending_click_message = f"대기 중인 클릭 {len(pending)}건 저장됨"
    return True, value


def apply_pending_clicks():
    pending = list(st.session_state.get("pending_clicks", []))
    if not pending:
        return 0

    df = st.session_state.df_extracted.copy()
    applied = 0
    for item in pending:
        row_idx = int(item.get("row_idx", -1))
        if 0 <= row_idx < len(df):
            df.at[row_idx, "Value"] = item.get("value")
            df.at[row_idx, "x_pixel"] = int(item.get("x_pixel", 0))
            df.at[row_idx, "y_pixel"] = int(item.get("y_pixel", 0))
            applied += 1

    st.session_state.df_extracted = df
    st.session_state.pending_clicks = []
    st.session_state.pending_click_message = f"{applied}건 일괄 적용 완료"
    return applied

# =========================
# Stable single-row selection helpers
# =========================

def sync_single_selection(df: pd.DataFrame, memory_key: str) -> tuple[pd.DataFrame, int | None]:
    """
    data_editor의 체크박스 선택 상태를 단일 선택으로 안정화하고,
    rerun 이후에도 마지막 선택 행을 유지합니다.
    """
    if df is None or len(df) == 0:
        st.session_state[memory_key] = None
        return df, None

    out = df.copy().reset_index(drop=True)
    if 'selected' not in out.columns:
        out.insert(0, 'selected', False)

    selected_indices = out.index[out['selected'] == True].tolist()
    remembered_idx = st.session_state.get(memory_key)

    active_idx = None
    if selected_indices:
        # 여러 개가 동시에 체크되면 마지막 체크된 행만 유지
        active_idx = selected_indices[-1]
    elif remembered_idx is not None and 0 <= remembered_idx < len(out):
        active_idx = remembered_idx

    out['selected'] = False
    if active_idx is not None and 0 <= active_idx < len(out):
        out.at[active_idx, 'selected'] = True
        st.session_state[memory_key] = int(active_idx)
    else:
        st.session_state[memory_key] = None

    return out, st.session_state[memory_key]

# =========================
# AgGrid 단일 선택 표 렌더링 헬퍼
# =========================

def render_single_select_table(
    df: pd.DataFrame,
    memory_key: str,
    table_key: str,
    height: int,
    editable_cols: list[str],
    numeric_cols: list[str] | None = None,
    hidden_cols: list[str] | None = None,
):
    """
    AgGrid가 가능하면 AgGrid를 사용하고, 아니면 기존 data_editor로 fallback 합니다.
    단일 선택 + 마지막 선택 행 기억을 유지합니다.
    """
    numeric_cols = numeric_cols or []
    hidden_cols = hidden_cols or []

    if df is None:
        df = pd.DataFrame()

    work_df = df.copy().reset_index(drop=True)
    if 'selected' not in work_df.columns:
        work_df.insert(0, 'selected', False)

    remembered_idx = st.session_state.get(memory_key)

    use_aggrid = (
        AGGRID_AVAILABLE
        and not DEBUG_DISABLE_AGGRID
        and not st.session_state.get("aggrid_runtime_disabled", False)
    )

    if use_aggrid:
        grid_df = work_df.copy()
        grid_df.insert(0, "__row_id__", range(len(grid_df)))

        gb = GridOptionsBuilder.from_dataframe(grid_df)
        gb.configure_default_column(editable=False, resizable=True, sortable=True, filter=False)
        gb.configure_selection(
            selection_mode="single",
            use_checkbox=True,
            pre_selected_rows=[remembered_idx] if remembered_idx is not None and 0 <= remembered_idx < len(grid_df) else [],
        )

        gb.configure_column("__row_id__", hide=True)
        if 'selected' in grid_df.columns:
            gb.configure_column("selected", hide=True)

        for col in editable_cols:
            if col in grid_df.columns:
                gb.configure_column(col, editable=True)

        for col in numeric_cols:
            if col in grid_df.columns:
                gb.configure_column(col, type=["numericColumn"], editable=(col in editable_cols))

        for col in hidden_cols:
            if col in grid_df.columns:
                gb.configure_column(col, hide=True)

        grid_options = gb.build()
        grid_options["suppressRowClickSelection"] = False
        grid_options["rowHeight"] = 32
        grid_options["headerHeight"] = 34
        grid_options["domLayout"] = "normal"

        try:
            response = AgGrid(
                grid_df,
                gridOptions=grid_options,
                data_return_mode=DataReturnMode.AS_INPUT,
                update_mode=GridUpdateMode.MODEL_CHANGED | GridUpdateMode.SELECTION_CHANGED,
                allow_unsafe_jscode=False,
                fit_columns_on_grid_load=False,
                height=height,
                theme="streamlit",
                key=table_key,
                reload_data=False,
            )

            updated_df = pd.DataFrame(response["data"]).copy()
            selected_rows = response.get("selected_rows", [])
            active_idx = None
            if selected_rows:
                selected_row = selected_rows[0]
                active_idx = int(selected_row["__row_id__"])
            elif remembered_idx is not None and 0 <= remembered_idx < len(updated_df):
                active_idx = int(remembered_idx)

            if "__row_id__" in updated_df.columns:
                updated_df = updated_df.drop(columns=["__row_id__"])
            if 'selected' not in updated_df.columns:
                updated_df.insert(0, 'selected', False)
            updated_df['selected'] = False
            if active_idx is not None and 0 <= active_idx < len(updated_df):
                updated_df.at[active_idx, 'selected'] = True
                st.session_state[memory_key] = int(active_idx)
            else:
                st.session_state[memory_key] = None

            return updated_df.reset_index(drop=True), st.session_state[memory_key]
        except Exception as e:
            st.session_state.aggrid_runtime_disabled = True
            st.session_state.aggrid_runtime_error = str(e)
            st.warning(f"AgGrid 실행 중 오류가 발생해 기본 표로 전환합니다: {e}")

    edited_df = st.data_editor(
        work_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        height=height,
        column_config={
            "selected": st.column_config.CheckboxColumn("선택", default=False),
            **({col: st.column_config.NumberColumn(col, format="%.4f") for col in numeric_cols if col in work_df.columns})
        },
        key=table_key,
    )
    return sync_single_selection(edited_df.copy(), memory_key)

# =========================
# 표시용 이미지 생성
# =========================
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

    is_horizontal = "Horizontal" in st.session_state.orientation
    
    # 💡 [신규] 축(Axis) 위치를 동적으로 감지하여 시각화 및 침범 차단
    gray = cv2.cvtColor(st.session_state.image_cv, cv2.COLOR_BGR2GRAY)
    _, binary_inv = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    
    if is_horizontal:
        kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, int(w * 0.2)), 1))
        row_counts = np.sum(cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel_h), axis=1)
        axis_pos = int(np.argmax(row_counts)) if np.any(row_counts > 0) else int(h * 0.9)
        
        # 🟢 감지된 가로형 기준축(X축)을 초록색 실선으로 명확히 표시
        cv2.line(display_img, (0, axis_pos), (w, axis_pos), (0, 255, 0), 2)
    else:
        # 💡 [끊긴 축 대응 로직 동일 적용] 
        kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, int(w * 0.2)), 1))
        horiz_lines = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel_h)
        row_counts_h = np.sum(horiz_lines, axis=1)
        y_indices = np.where(row_counts_h > 0)[0]
        axis_y_0 = int(max(y_indices)) if len(y_indices) > 0 else int(h * 0.9)
        
        x_line_pixels = np.where(horiz_lines[axis_y_0, :] > 0)[0]
        x_start_px = x_line_pixels[0] if len(x_line_pixels) > 0 else int(w * 0.1)

        kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, int(h * 0.3))))
        vert_lines = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel_v)
        col_counts_v = np.sum(vert_lines, axis=0)
        
        search_range = col_counts_v[max(0, x_start_px - 30) : min(w, x_start_px + 30)]
        if np.any(search_range > 0):
            axis_pos = max(0, x_start_px - 30) + int(np.argmax(search_range))
        else:
            axis_pos = x_start_px
            
        # 🟢 감지된 세로형 기준축(Y축)을 초록색 실선으로 명확히 표시
        cv2.line(display_img, (axis_pos, 0), (axis_pos, h), (0, 255, 0), 2)

    # 파란선(기본)과 빨간선(선택됨)을 따로 그리기 위한 오버레이
    calib_overlay_blue = display_img.copy()
    calib_overlay_red = display_img.copy()
    has_selected_calib = False

    for _, row in st.session_state.df_calibration.dropna(subset=['Pixel']).iterrows():
        px = int(row['Pixel'])
        is_selected = row.get('selected', False)
        
        if is_selected:
            has_selected_calib = True
            # 선택된 선은 빨간색(0, 0, 255)으로 조금 더 굵게(3) 그림
            if is_horizontal: cv2.line(calib_overlay_red, (px, axis_pos), (px, h), (0, 0, 255), 3)
            else: cv2.line(calib_overlay_red, (0, px), (axis_pos, px), (0, 0, 255), 3)
        else:
            # 선택 안 된 선은 기존처럼 파란색(255, 0, 0)으로 그림
            if is_horizontal: cv2.line(calib_overlay_blue, (px, axis_pos), (px, h), (255, 0, 0), 2)
            else: cv2.line(calib_overlay_blue, (0, px), (axis_pos, px), (255, 0, 0), 2)
            
    # 파란선 반투명(40%) 적용
    display_img = cv2.addWeighted(calib_overlay_blue, 0.4, display_img, 0.6, 0)
    # 선택된 빨간선이 있으면 그 위에 반투명(70%)으로 덧그림
    if has_selected_calib:
        display_img = cv2.addWeighted(calib_overlay_red, 0.7, display_img, 0.3, 0)

    ensure_cursor_y()
    # cursor_y 변수명은 유지하지만, 가로형일 때는 사실상 X좌표를 의미합니다.
    cursor_pos = max(0, min((w if is_horizontal else h) - 1, int(st.session_state.cursor_y)))
    
    overlay = display_img.copy()
    
    if is_horizontal:
        # 💡 [가로형] 수직선(세로 방향의 선)을 그림
        cv2.line(overlay, (cursor_pos, 0), (cursor_pos, h), (0, 255, 255), 2)
        display_img = cv2.addWeighted(overlay, 0.35, display_img, 0.65, 0)
        # 클릭하기 편하게 위쪽에 손잡이 사각형을 그림
        cv2.rectangle(display_img, (max(0, cursor_pos - 4), 0), (min(w - 1, cursor_pos + 4), 18), (0, 255, 255), -1)
    else:
        # 💡 [세로형] 기존처럼 수평선(가로 방향의 선)을 그림
        cv2.line(overlay, (0, cursor_pos), (w, cursor_pos), (0, 255, 255), 2)
        display_img = cv2.addWeighted(overlay, 0.35, display_img, 0.65, 0)
        # 클릭하기 편하게 왼쪽에 손잡이 사각형을 그림
        cv2.rectangle(display_img, (0, max(0, cursor_pos - 4)), (18, min(h - 1, cursor_pos + 4)), (0, 255, 255), -1)

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

    st.caption(
        "디버그 설정: "
        f"AgGrid={'OFF' if DEBUG_DISABLE_AGGRID else 'ON'} / "
        f"Canvas={'OFF' if DEBUG_DISABLE_CANVAS else 'ON'} / "
        f"ImageCoords={'OFF' if DEBUG_DISABLE_IMAGE_COORDS else 'ON'}"
    )

    if st.session_state.image_cv is not None:
        col_table, col_img = st.columns([0.9, 1.8], gap="large")

        if st.button("🤖 1차 자동 분석 (라벨 및 모든 축 감지)", use_container_width=True):
            with st.spinner("이미지 방향 및 물리 구조 분석 중..."):
                try:
                    is_horizontal = "Horizontal" in st.session_state.orientation
                    
                    # 1. 💡 그래프 방향에 따른 물리적 눈금 검출
                    if is_horizontal:
                        all_val_pixels, axis_y_0 = auto_detect_all_x_val_ticks(st.session_state.image_cv)
                        # 가로형일 때 클릭 보정 기준선(Baseline)은 Y축(세로선)이 됨
                        st.session_state.baseline_y = axis_y_0 
                    else:
                        all_val_pixels, y_axis_x = auto_detect_all_y_ticks(st.session_state.image_cv)
                        # 세로형일 때 기준선(Baseline)은 제일 아래쪽 눈금
                        st.session_state.baseline_y = all_val_pixels[0] if len(all_val_pixels) > 0 else int(st.session_state.image_cv.shape[0] * 0.9)
                        
                    # 2. 💡 방향 정보(orientation)를 제미니에게 전달!
                    data, err = run_gemini_analysis(st.session_state.image_pil, tick_count=len(all_val_pixels), orientation=st.session_state.orientation)
                    
                    if err:
                        st.warning(err)
                    elif data:
                        st.session_state.plot_type = str(data.get("plot_type", "Unknown"))
                        
                        # 💡 키 이름이 y_axis_labels에서 value_labels로 범용적으로 변경됨
                        y_vals = data.get("value_labels", [])
                        
                        st.info(f"🔍 물리적 눈금 감지: {len(all_val_pixels)}개 / AI 수치 인식: {len(y_vals)}개")
                        
                        padded_y_vals = []
                        for i in range(len(all_val_pixels)):
                            if i < len(y_vals):
                                parsed_val = parse_axis_value_label(y_vals[i])
                                padded_y_vals.append(parsed_val)
                            else:
                                padded_y_vals.append(None)
                        
                        if len(all_val_pixels) >= 2:
                            calib_data = {
                                "selected": [False] * len(all_val_pixels),
                                "Pixel": all_val_pixels, # 가로형이면 X좌표, 세로형이면 Y좌표가 들어감
                                "Value": padded_y_vals
                            }
                            st.session_state.df_calibration = pd.DataFrame(calib_data)
                            failed_labels = [str(y_vals[i]) for i in range(min(len(y_vals), len(padded_y_vals))) if padded_y_vals[i] is None]
                            if failed_labels:
                                st.warning(f"일부 축 라벨을 숫자로 변환하지 못했습니다: {failed_labels}")
                            st.success(f"총 {len(all_val_pixels)}개의 물리적 픽셀을 캘리브레이션 표에 등록했습니다.")
                        else:
                            st.warning("눈금을 충분히 찾지 못했습니다. 수동으로 입력해 주세요.")

                        # 💡 키 이름이 x_labels에서 category_labels로 범용적으로 변경됨
                        labels = [str(x).strip() for x in data.get("category_labels", []) if str(x).strip()]
                        groups = [str(g).strip() for g in data.get("group_labels", []) if str(g).strip()]
                        
                        st.session_state.x_labels_input = ", ".join(labels)
                        st.session_state.groups_input = ", ".join(groups)
                        
                        records = []
                        for lbl in labels:
                            for grp in (groups if groups else ["N/A"]):
                                records.append({
                                    "selected": False, "figure_name": st.session_state.figure_name, 
                                    "X_Label": lbl, "Group": grp, "Value": None, 
                                    "Type": st.session_state.plot_type, "x_pixel": None, "y_pixel": None
                                })
                                
                        st.session_state.df_extracted = pd.DataFrame(records)
                        st.success("항목 라벨(카테고리) 및 범례(그룹) 표 생성 완료!")
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
                    x_centers = auto_detect_x_ticks(st.session_state.image_cv, y_axis_x, st.session_state.baseline_y)
                    
                    if not x_centers:
                        st.warning("X축 눈금(막대 중심)을 감지하지 못했습니다.")
                    else:
                        st.success(f"물리적 X축 기준점을 감지했습니다. 에이전트를 시작합니다.")
                        client = get_vertexai_client(find_api_key_file("vertex.json"))
                        
                        df = st.session_state.df_extracted
                        unique_labels = df['X_Label'].unique().tolist()
                        
                        # 고유 라벨(예: 4개)과 물리적 X 중심점(4개) 매핑
                        label_to_x = {}
                        for i, lbl in enumerate(unique_labels):
                            if i < len(x_centers):
                                label_to_x[lbl] = x_centers[i]
                        
                        # 💡 [핵심] 표의 모든 행(그룹 포함)을 순회하며 에이전트 실행
                        for idx, row in df.iterrows():
                            x_label = row['X_Label']
                            group_name = row.get('Group', 'N/A')
                            
                            # 이 라벨의 X 중심점 가져오기 (없으면 건너뜀)
                            target_x = label_to_x.get(x_label)
                            if target_x is None: continue
                                
                            initial_y = int(st.session_state.baseline_y * 0.8) 
                            
                            # 에이전트 실행 (라벨과 그룹명 전달)
                            final_y = autonomous_y_finder(
                                st.session_state.image_cv, 
                                target_x, 
                                initial_y, 
                                st.session_state.y_max_pixel,  
                                client, 
                                status_text,
                                x_label,
                                group_name
                            )
                            
                            # 💡 기존 로직 대신 다중 캘리브레이션/로그 스케일을 지원하는 calculate_custom_value 사용
                            value = calculate_custom_value(final_y)
                            st.session_state.df_extracted.at[idx, "Value"] = value
                            st.session_state.df_extracted.at[idx, "x_pixel"] = target_x
                            st.session_state.df_extracted.at[idx, "y_pixel"] = final_y
                            
                            progress_bar.progress((idx + 1) / len(df))
                        
                        status_text.success("🎉 에이전트가 모든 다중 그룹 데이터의 정밀 추출을 완료했습니다!")
                        st.rerun()

                except Exception as e:
                    st.error(f"에이전트 실행 중 오류 발생: {e}")
    else:
        st.info("👈 왼쪽 사이드바에서 이미지 파일을 업로드해 주세요.")
        st.image("https://via.placeholder.com/800x400.png?text=Waiting+for+Upload", use_column_width=True)

    st.header("2. 그래프 설정")
    st.session_state.figure_name = st.text_input("Figure name", value=st.session_state.figure_name, placeholder="예: Figure 2B")
    
    # 방향, 로그 스케일, 이미지 줌
    st.session_state.orientation = st.radio("그래프 방향", ["Vertical (세로형)", "Horizontal (가로형)"])
    st.session_state.is_log_scale = st.checkbox("Log Scale (로그 축 사용)", value=st.session_state.is_log_scale)
    st.session_state.image_zoom = st.slider("이미지 줌 (%)", 50, 300, st.session_state.image_zoom, 10)

    # [신규] 돋보기 영역을 취소하고 싶을 때 누르는 버튼
    if st.session_state.get("zoom_region") is not None:
        if st.button("↩️ 돋보기 영역 리셋", use_container_width=True):
            st.session_state.zoom_region = None
            st.rerun()

    st.divider()
    st.header("3. 다중 눈금 캘리브레이션")
    st.info("잘린 축 대응: 눈금의 픽셀(Pixel)과 단위(Value)를 여러 개 입력하세요.")

    if 'selected' not in st.session_state.df_calibration.columns:
        st.session_state.df_calibration.insert(0, 'selected', False)

    # 💡 [신규] 표 중간 삽입/삭제 버튼 추가
    calib_btn1, calib_btn2 = st.columns(2)
    with calib_btn1:
        if st.button("➕ 선택 행 아래 삽입", use_container_width=True):
            idx = st.session_state.get("selected_calib_idx_memory")
            if idx is not None and 0 <= idx < len(st.session_state.df_calibration):
                df = st.session_state.df_calibration
                new_row = pd.DataFrame([{"selected": False, "Pixel": None, "Value": None}])
                st.session_state.df_calibration = pd.concat([df.iloc[:idx+1], new_row, df.iloc[idx+1:]]).reset_index(drop=True)
                st.session_state.selected_calib_idx_memory = idx + 1
                st.rerun()
            else:
                st.warning("먼저 표에서 기준이 될 행을 선택하세요.")
    with calib_btn2:
        if st.button("🗑️ 선택 행 삭제", use_container_width=True):
            idx = st.session_state.get("selected_calib_idx_memory")
            if idx is not None and 0 <= idx < len(st.session_state.df_calibration):
                st.session_state.df_calibration = st.session_state.df_calibration.drop(index=idx).reset_index(drop=True)
                st.session_state.selected_calib_idx_memory = None
                st.rerun()
            else:
                st.warning("삭제할 눈금 행을 먼저 선택하세요.")

    if AGGRID_AVAILABLE and not DEBUG_DISABLE_AGGRID and not st.session_state.get("aggrid_runtime_disabled", False):
        st.caption("캘리브레이션 표는 AgGrid로 표시됩니다. 스크롤/선택 유지가 기본 표보다 더 안정적입니다.")
    elif DEBUG_DISABLE_AGGRID:
        st.caption("디버그 모드: AgGrid를 강제로 비활성화하고 기본 표를 사용합니다.")
    elif AGGRID_AVAILABLE and st.session_state.get("aggrid_runtime_disabled", False):
        st.caption(f"AgGrid가 설치되어 있지만 현재 환경과 충돌해 기본 표로 전환되었습니다: {st.session_state.get('aggrid_runtime_error')}")
    else:
        st.caption("AgGrid가 설치되지 않아 기본 표를 사용 중입니다. 설치: pip install streamlit-aggrid")

    # 표 렌더링
    st.session_state.df_calibration, active_idx = render_single_select_table(
        st.session_state.df_calibration,
        memory_key="selected_calib_idx_memory",
        table_key="df_editor_calibration",
        height=320,
        editable_cols=["Pixel", "Value"],
        numeric_cols=["Pixel", "Value"],
    )

    # 미세조정 버튼
    if active_idx is not None:
        st.write("🎯 선택된 눈금 미세조정:")
        
        # 💡 [신규] 축 방향 확인
        is_horizontal = "Horizontal" in st.session_state.orientation
        
        c1, c2, c3 = st.columns([1, 1, 2])
        with c3:
            move_px = st.number_input("이동 px", min_value=1, value=1, step=1, key="calib_move_step")
            
        if is_horizontal:
            with c1:
                if st.button("◀ 왼쪽", use_container_width=True, key="calib_left"):
                    st.session_state.df_calibration.at[active_idx, 'Pixel'] -= move_px
                    st.rerun()
            with c2:
                if st.button("오른쪽 ▶", use_container_width=True, key="calib_right"):
                    st.session_state.df_calibration.at[active_idx, 'Pixel'] += move_px
                    st.rerun()
        else:
            with c1:
                if st.button("▲ 위로", use_container_width=True, key="calib_up"):
                    st.session_state.df_calibration.at[active_idx, 'Pixel'] -= move_px
                    st.rerun()
            with c2:
                if st.button("▼ 아래로", use_container_width=True, key="calib_down"):
                    st.session_state.df_calibration.at[active_idx, 'Pixel'] += move_px
                    st.rerun()

    st.divider()
    st.header("4. 라벨 및 다중 그룹(색상)")
    x_labels_text = st.text_area("X축 라벨 (콤마로 구분)", value=st.session_state.x_labels_input)
    groups_text = st.text_area("그룹/색상명 (선택, 콤마 구분)", value=st.session_state.groups_input, placeholder="예: Blank, Syn-3")
    
    if st.button("라벨 표 자동 생성", use_container_width=True):
        st.session_state.x_labels_input = x_labels_text
        st.session_state.groups_input = groups_text
        labels = [x.strip() for x in x_labels_text.split(",") if x.strip()]
        groups = [g.strip() for g in groups_text.split(",") if g.strip()]
        
        # 💡 신규: X라벨과 그룹을 조합(Cartesian Product)하여 표 생성
        records = []
        for lbl in labels:
            for grp in (groups if groups else ["N/A"]):
                records.append({
                    "selected": False, "figure_name": st.session_state.figure_name, 
                    "X_Label": lbl, "Group": grp, "Value": None, 
                    "Type": "Manual", "x_pixel": None, "y_pixel": None
                })
        st.session_state.df_extracted = pd.DataFrame(records)
        st.success(f"총 {len(records)}개의 행을 생성했습니다.")

# =========================
# 메인 화면
# =========================
if st.session_state.image_cv is not None:
    col_table, col_img = st.columns([0.9, 1.8], gap="large")

    with col_table:
        st.subheader("5. 데이터 매칭 표")
        if AGGRID_AVAILABLE and not DEBUG_DISABLE_AGGRID and not st.session_state.get("aggrid_runtime_disabled", False):
            st.caption("AgGrid 단일선택 표를 사용합니다. 기본 표보다 스크롤/선택 유지가 더 안정적입니다.")
        elif DEBUG_DISABLE_AGGRID:
            st.caption("디버그 모드: AgGrid를 강제로 비활성화하고 기본 표를 사용합니다.")
        elif AGGRID_AVAILABLE and st.session_state.get("aggrid_runtime_disabled", False):
            st.caption(f"AgGrid가 설치되어 있지만 현재 환경과 충돌해 기본 표로 전환되었습니다: {st.session_state.get('aggrid_runtime_error')}")
        else:
            st.caption("체크박스 선택은 1개 행만 유지되도록 고정했습니다. AgGrid가 없어서 기본 표를 사용 중이며, 스크롤 위치는 rerun 때 완전 고정되지 않을 수 있습니다.")
        # 💡 "Group" 컬럼 추가
        required_cols = ["selected", "figure_name", "X_Label", "Group", "Value", "Type", "x_pixel", "y_pixel"]
        if "df_extracted" not in st.session_state or st.session_state.df_extracted is None:
            st.session_state.df_extracted = pd.DataFrame(columns=required_cols)
        for col in required_cols:
            if col not in st.session_state.df_extracted.columns:
                st.session_state.df_extracted[col] = False if col == "selected" else None

        st.session_state.df_extracted = st.session_state.df_extracted[required_cols].reset_index(drop=True)

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("행 추가", use_container_width=True):
                new_row = pd.DataFrame([{
                    "selected": False,
                    "figure_name": st.session_state.figure_name,
                    "X_Label": None,
                    "Group": "N/A",
                    "Value": None,
                    "Type": st.session_state.plot_type,
                    "x_pixel": None,
                    "y_pixel": None,
                }])
                st.session_state.df_extracted = pd.concat(
                    [st.session_state.df_extracted, new_row], ignore_index=True
                )
                st.rerun()

        with btn_col2:
            if st.button("선택 행 삭제", use_container_width=True):
                current_df, current_selected_idx = sync_single_selection(
                    st.session_state.df_extracted.copy(), "selected_row_idx_memory"
                )
                if current_selected_idx is not None:
                    st.session_state.df_extracted = current_df.drop(index=current_selected_idx).reset_index(drop=True)
                    st.session_state.selected_row_idx_memory = None
                    st.rerun()

        st.session_state.df_extracted, selected_row_idx = render_single_select_table(
            st.session_state.df_extracted,
            memory_key="selected_row_idx_memory",
            table_key="df_editor_main",
            height=420,
            editable_cols=["figure_name", "X_Label", "Group", "Value", "Type"],
            numeric_cols=["Value", "x_pixel", "y_pixel"],
        )
        
        # CSV 다운로드 추가
        st.divider()
        csv_data = st.session_state.df_extracted.to_csv(index=False).encode('utf-8')
        st.download_button("📥 현재 표를 CSV로 저장", data=csv_data, file_name=f"LNPDB_{st.session_state.figure_name or 'extracted'}.csv", mime="text/csv", use_container_width=True)

    with col_img:
        st.subheader("6. 그래프 분석 (왼쪽: 원본 이동 및 영역 지정 / 오른쪽: 클릭 추출)")
        img_rgb = build_display_image(selected_row_idx)

        if img_rgb is not None:
            is_horizontal = "Horizontal" in st.session_state.get("orientation", "Vertical")
            orig_h, orig_w = img_rgb.shape[:2]

            # 💡 [해결 1] 강제 픽셀 고정 대신, 내 모니터에 딱 맞게 캔버스 너비를 조절할 수 있는 슬라이더 추가!
            canvas_display_width = st.slider("🛠️ 왼쪽 원본 화면 너비 조절 (화면이 가려지거나 겹치면 이 바를 줄이세요)", 300, 1000, 550, 50)

            img_col_left, img_col_right = st.columns([1, 1])

            # ==========================================
            # 👈 왼쪽 화면: 원본 스크롤 및 드래그 영역 지정
            # ==========================================
            with img_col_left:
                st.caption("👈 (1) 아래 바를 움직여 원본을 이동하고, (2) 확대할 부분을 드래그하세요")
                
                zoom_factor = st.session_state.get("image_zoom", 100) / 100.0
                view_w = int(orig_w / zoom_factor)
                
                max_pan_x = max(0, orig_w - view_w)
                if max_pan_x > 0:
                    pan_x = st.slider("↔️ 원본 이미지 좌우 스크롤", 0, max_pan_x, 0, key="orig_pan_slider")
                else:
                    pan_x = 0
                
                bg_img_cropped = img_rgb[:, pan_x : pan_x + view_w].copy()

                if st.session_state.get("zoom_region") is not None:
                    zx, zy, zw, zh = st.session_state.zoom_region
                    box_x = zx - pan_x
                    cv2.rectangle(bg_img_cropped, (box_x, zy), (box_x+zw, zy+zh), (0, 165, 255), 4)

                pil_image_for_canvas = Image.fromarray(bg_img_cropped)
                
                if DEBUG_DISABLE_CANVAS:
                    st.info("디버그 모드: drawable canvas를 비활성화했습니다. 현재는 원본 이미지만 표시합니다.")
                    st.image(pil_image_for_canvas, use_column_width=True, caption="원본 보기 (canvas 비활성화)")
                else:
                    canvas_result = st_canvas(
                        fill_color="rgba(255, 165, 0, 0.1)",
                        stroke_width=2,
                        stroke_color="#FFA500",
                        background_image=pil_image_for_canvas,
                        update_streamlit=False,
                        height=pil_image_for_canvas.height * (canvas_display_width / pil_image_for_canvas.width),
                        width=canvas_display_width,
                        drawing_mode="rect",
                        key="zoom_canvas_drag",
                    )
                    
                    if canvas_result.json_data is not None:
                        objs = canvas_result.json_data["objects"]
                        if len(objs) > 0:
                            last_obj = objs[-1]
                            if last_obj["type"] == "rect":
                                canvas_scale = view_w / canvas_display_width
                                
                                dr_x1 = int(round(last_obj["left"] * canvas_scale)) + pan_x
                                dr_y1 = int(round(last_obj["top"] * canvas_scale))
                                dr_w = int(round(last_obj["width"] * canvas_scale))
                                dr_h = int(round(last_obj["height"] * canvas_scale))
                                
                                if dr_w > 10 and dr_h > 10:
                                    new_region = (dr_x1, dr_y1, dr_w, dr_h)
                                    if st.session_state.get("zoom_region") != new_region:
                                        st.session_state.zoom_region = new_region
                                        st.rerun()

            # ==========================================
            # 👉 오른쪽 화면: 돋보기 및 클릭 추출
            # ==========================================
            with img_col_right:
                if st.session_state.get("zoom_region") is None:
                    st.caption("🔍 대기 중 (왼쪽에서 드래그하면 나타납니다)")
                    st.image("https://via.placeholder.com/800x600.png?text=Drag+on+Left+to+Zoom", use_column_width=True)
                else:
                    st.caption("🎯 여기서 막대를 클릭하여 수치 추출")
                    z_x, z_y, z_w, z_h = st.session_state.zoom_region
                    
                    cropped_img = img_rgb[z_y:z_y+z_h, z_x:z_x+z_w]
                    
                    if DEBUG_DISABLE_IMAGE_COORDS:
                        st.info("디버그 모드: image click coordinates 컴포넌트를 비활성화했습니다.")
                        st.image(cropped_img, use_column_width=True, caption="돋보기 화면 (클릭 비활성화)")
                    else:
                        try:
                            ratio = z_w / canvas_display_width
                            display_h = int(z_h / ratio)
                            resized_crop_pil = Image.fromarray(cropped_img).resize((canvas_display_width, display_h))
                            clicked = streamlit_image_coordinates(
                                resized_crop_pil,
                                key="lnp_image_zoom_click"
                            )

                            if clicked is not None:
                                click_crop_x = int(clicked["x"] * ratio)
                                click_crop_y = int(clicked["y"] * ratio)
                                clicked_x = max(0, min(orig_w - 1, click_crop_x + z_x))
                                clicked_y = max(0, min(orig_h - 1, click_crop_y + z_y))
                                click_signature = f"{clicked_x}_{clicked_y}"

                                if st.session_state.last_click_signature != click_signature:
                                    st.session_state.last_click_x = clicked_x
                                    st.session_state.last_click_y = clicked_y
                                    st.session_state.last_click_signature = click_signature

                                    target_pixel = clicked_x if is_horizontal else clicked_y
                                    st.session_state.cursor_y = target_pixel

                                    if selected_row_idx is not None:
                                        ok, calc_val = queue_click_for_selected_row(selected_row_idx, clicked_x, clicked_y)
                                        if ok:
                                            st.session_state.pending_click_message = (
                                                f"선택 행 {selected_row_idx + 1} 클릭 저장 완료 (Value={calc_val})"
                                            )
                                    else:
                                        st.session_state.pending_click_message = "클릭은 저장했지만 선택된 행이 없습니다."
                        except Exception as e:
                            st.image(cropped_img, use_column_width=True, caption="돋보기 화면 (클릭 오류)")
                            st.warning(f"image_coordinates 렌더링 오류: {e}")
                            st.code(traceback.format_exc())

                    pending_clicks = st.session_state.get("pending_clicks", [])
                    pending_msg = st.session_state.get("pending_click_message")
                    if pending_msg:
                        st.info(pending_msg)
                    if pending_clicks:
                        st.caption(f"현재 일괄 적용 대기: {len(pending_clicks)}건")

            # 방향키 및 수동 적용 버튼 (에러 방지용 key 추가 완료)
            # ==========================================
            ensure_cursor_y()
            st.write("---")
            c1, c2, c3, c4 = st.columns([1, 1, 2, 2])
            
            # 💡 [신규] 축 방향에 따른 UI 분기
            if is_horizontal:
                with c1:
                    if st.button("◀ 커서 왼쪽", use_container_width=True, key="btn_cursor_left"):
                        move_cursor(-int(st.session_state.cursor_step))
                        st.rerun()
                with c2:
                    if st.button("커서 오른쪽 ▶", use_container_width=True, key="btn_cursor_right"):
                        move_cursor(int(st.session_state.cursor_step))
                        st.rerun()
            else:
                with c1:
                    if st.button("▲ 커서 위", use_container_width=True, key="btn_cursor_up"):
                        move_cursor(-int(st.session_state.cursor_step))
                        st.rerun()
                with c2:
                    if st.button("▼ 커서 아래", use_container_width=True, key="btn_cursor_down"):
                        move_cursor(int(st.session_state.cursor_step))
                        st.rerun()

            with c3: st.number_input("이동 px", min_value=1, step=1, key="cursor_step")
            with c4: st.number_input("현재 커서 좌표", min_value=0, step=1, key="cursor_y")

            apply_col1, apply_col2 = st.columns(2)

            with apply_col1:
                if selected_row_idx is not None:
                    if st.button("수동 커서 위치 저장", use_container_width=True, key="btn_cursor_apply"):
                        clicked_x = st.session_state.last_click_x if st.session_state.last_click_x is not None else 0
                        clicked_y = int(st.session_state.cursor_y)
                        ok, result = queue_click_for_selected_row(selected_row_idx, clicked_x, clicked_y)
                        if ok:
                            st.success(f"저장 완료: Value={result}")
                        else:
                            st.warning(result)
                else:
                    st.button("수동 커서 위치 저장", use_container_width=True, key="btn_cursor_apply_disabled", disabled=True)

            with apply_col2:
                pending_count = len(st.session_state.get("pending_clicks", []))
                if st.button(
                    f"저장된 클릭 일괄 적용 ({pending_count})",
                    use_container_width=True,
                    key="btn_apply_pending_clicks",
                    disabled=(pending_count == 0),
                ):
                    applied = apply_pending_clicks()
                    if applied > 0:
                        st.success(f"{applied}건을 표에 반영했습니다.")
                        st.rerun()

if __name__ == "__main__":
    from streamlit.web import cli
    from streamlit import runtime

    if not runtime.exists():
        sys.argv = ["streamlit", "run", __file__]
        sys.exit(cli.main())

# python -m streamlit run C:\Users\kogun\PycharmProjects\LNPDB_Articles_Extraction\4_Extract_Exp_Vals\Exp_Vals_From_Figs\value_extractor_5.py
# python -m streamlit run /Users/kogeon/python_projects_path/LNPDB_Articles_Extraction/4_Extract_Exp_Vals/Exp_Vals_From_Figs/value_extractor_8.py