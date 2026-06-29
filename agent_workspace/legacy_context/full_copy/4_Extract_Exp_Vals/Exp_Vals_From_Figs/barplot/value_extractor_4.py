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
        "groups_input": "", # 💡 다중 색상/그룹 입력용
        "orientation": "Vertical (세로형)", # 💡 가로/세로 방향
        "is_log_scale": False, # 💡 로그 스케일 여부
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

# =========================
# Gemini 분석 & 에이전트 루프
# =========================
def run_gemini_analysis(image_pil, tick_count=None):
    if not API_AVAILABLE:
        return None, f"Gemini API 모듈 import 실패: {API_IMPORT_ERROR}"
    try:
        key_path = find_api_key_file("vertex-490605-8d0be916872a.json")
        client = get_vertexai_client(key_path)

        # 💡 [핵심] OpenCV가 찾은 물리적 눈금 개수를 프롬프트에 동적으로 주입
        tick_instruction = ""
        if tick_count is not None:
            tick_instruction = f"""
            [중요 지시사항]
            OpenCV를 통해 물리적으로 총 {tick_count}개의 눈금(또는 축 끊김 표시선)이 감지되었습니다. 
            따라서 'y_axis_labels' 배열의 원소 개수는 반드시 정확히 {tick_count}개여야 합니다.
            만약 Y축이 중간에 생략된(Broken axis) 형태라서 끊어진 부분을 나타내는 평행선도 눈금으로 감지되었다면, 
            해당 빈 공간에는 끊어지기 직전의 값(예: 100)을 중복으로 채워 넣어서라도 배열 길이를 정확히 {tick_count}개로 맞추세요.
            (예시: [0, 25, 50, 75, 100, 100, 100, 250, 500, 750, 1000])
            """

        prompt = f"""
        당신은 그래프 전문 분석가입니다. 이미지에서 다음 정보를 JSON으로 반환하세요:
        Required format:
        {{
          "y_axis_labels": [1, 10, 100, 1000], // Y축 눈금 옆에 써진 숫자들을 '아래에서 위 방향' 순서대로 추출. {tick_instruction}
          "x_labels": ["label1", "label2", "..."], // X축의 모든 항목 이름 리스트
          "group_labels": ["Control", "APOE KO"], // 범례(Legend)에 있는 그룹/색상 이름 리스트 (없으면 빈 리스트 [])
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
    value = calculate_value_from_click(clicked_y)
    st.session_state.df_extracted.at[selected_row_idx, "Value"] = value
    st.session_state.df_extracted.at[selected_row_idx, "x_pixel"] = int(clicked_x)
    st.session_state.df_extracted.at[selected_row_idx, "y_pixel"] = int(clicked_y)
    return True, value

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
        # 버튼 1: 기존 자동 분석 (축 감지 + 라벨 파싱) -> 다중 눈금 물리 감지 로직으로 교체
        if st.button("🤖 1차 자동 분석 (라벨 및 모든 축 감지)", use_container_width=True):
            with st.spinner("이미지 물리 구조 및 수치 분석 중..."):
                try:
                    # 1. 물리적 눈금 픽셀들 검출
                    all_y_pixels, y_axis_x = auto_detect_all_y_ticks(st.session_state.image_cv)
                    
                    # 기준선(바닥선)은 가장 아래쪽 눈금 또는 이미지 하단으로 설정
                    st.session_state.baseline_y = all_y_pixels[0] if len(all_y_pixels) > 0 else int(st.session_state.image_cv.shape[0] * 0.9)
                    
                    # 2. 💡 [수정됨] Gemini를 통한 텍스트 라벨 추출 (감지된 물리적 눈금 개수를 프롬프트에 전달)
                    data, err = run_gemini_analysis(st.session_state.image_pil, tick_count=len(all_y_pixels))
                    
                    if err:
                        st.warning(err)
                    elif data:
                        st.session_state.plot_type = str(data.get("plot_type", "Unknown"))
                        
                        # Y축 라벨(수치) 매칭
                        y_vals = data.get("y_axis_labels", [])
                        
                        st.info(f"🔍 물리적 눈금 감지: {len(all_y_pixels)}개 / AI 라벨 인식: {len(y_vals)}개")
                        
                        # 💡 [핵심 변경] 물리적 눈금 개수만큼 무조건 표에 등록하고, 부족한 숫자는 빈칸(None)으로 처리
                        padded_y_vals = []
                        for i in range(len(all_y_pixels)):
                            if i < len(y_vals):
                                try:
                                    clean_val = str(y_vals[i]).replace(',', '').replace(' ', '')
                                    padded_y_vals.append(float(clean_val))
                                except (ValueError, TypeError):
                                    padded_y_vals.append(None)
                            else:
                                padded_y_vals.append(None)
                        
                        if len(all_y_pixels) >= 2:
                            # 캘리브레이션 표 자동 생성 (아래에서 위 순서로 매칭)
                            calib_data = {
                                "selected": [False] * len(all_y_pixels), # 💡 선택 체크박스 추가
                                "Pixel": all_y_pixels,
                                "Value": padded_y_vals
                            }
                            st.session_state.df_calibration = pd.DataFrame(calib_data)
                            st.success(f"총 {len(all_y_pixels)}개의 물리적 픽셀을 보존했습니다. (어긋나거나 비어있는 수치는 표에서 직접 수정해 주세요)")
                        else:
                            st.warning("눈금을 충분히 찾지 못했습니다. 좌측 하단의 캘리브레이션 표에 수동으로 입력해 주세요.")

                        # X축 라벨 및 그룹(범례) 데이터 세팅
                        labels = [str(x).strip() for x in data.get("x_labels", []) if str(x).strip()]
                        groups = [str(g).strip() for g in data.get("group_labels", []) if str(g).strip()]
                        
                        # 사이드바 텍스트 입력칸 자동 채우기
                        st.session_state.x_labels_input = ", ".join(labels)
                        st.session_state.groups_input = ", ".join(groups)
                        
                        # 라벨과 그룹을 조합(Cartesian Product)하여 표 자동 생성
                        records = []
                        for lbl in labels:
                            # 그룹이 없으면 기본값 "N/A" 하나만 생성
                            for grp in (groups if groups else ["N/A"]):
                                records.append({
                                    "selected": False, "figure_name": st.session_state.figure_name, 
                                    "X_Label": lbl, "Group": grp, "Value": None, 
                                    "Type": st.session_state.plot_type, "x_pixel": None, "y_pixel": None
                                })
                                
                        st.session_state.df_extracted = pd.DataFrame(records)
                        st.success("X축 라벨 및 범례(그룹) 추출 및 표 생성 완료!")
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
                        client = get_vertexai_client(find_api_key_file("vertex-490605-8d0be916872a.json"))
                        
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
    
    # 💡 신규: 방향, 로그 스케일, 이미지 줌
    st.session_state.orientation = st.radio("그래프 방향", ["Vertical (세로형)", "Horizontal (가로형)"])
    st.session_state.is_log_scale = st.checkbox("Log Scale (로그 축 사용)", value=st.session_state.is_log_scale)
    st.session_state.image_zoom = st.slider("이미지 줌 (%)", 50, 300, st.session_state.image_zoom, 10)

    st.divider()
    st.header("3. 다중 눈금 캘리브레이션")
    st.info("잘린 축 대응: 눈금의 픽셀(Pixel)과 단위(Value)를 여러 개 입력하세요.")

    if 'selected' not in st.session_state.df_calibration.columns:
        st.session_state.df_calibration.insert(0, 'selected', False)

    # 💡 [신규] 표 중간 삽입/삭제 버튼 추가
    calib_btn1, calib_btn2 = st.columns(2)
    with calib_btn1:
        if st.button("➕ 선택 행 아래 삽입", use_container_width=True):
            sel_idxs = st.session_state.df_calibration.index[st.session_state.df_calibration['selected'] == True].tolist()
            if sel_idxs:
                idx = sel_idxs[0]
                df = st.session_state.df_calibration
                # 빈 행 생성 후 선택한 인덱스 바로 아래에 끼워넣기 (Pandas Concat)
                new_row = pd.DataFrame([{"selected": False, "Pixel": None, "Value": None}])
                st.session_state.df_calibration = pd.concat([df.iloc[:idx+1], new_row, df.iloc[idx+1:]]).reset_index(drop=True)
                st.rerun()
            else:
                st.warning("먼저 표에서 기준이 될 행을 체크하세요.")
    with calib_btn2:
        if st.button("🗑️ 선택 행 삭제", use_container_width=True):
            st.session_state.df_calibration = st.session_state.df_calibration[st.session_state.df_calibration['selected'] != True].reset_index(drop=True)
            st.rerun()

    # 표 렌더링
    edited_calib = st.data_editor(
        st.session_state.df_calibration, num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={"selected": st.column_config.CheckboxColumn("선택", default=False)}
    )
    st.session_state.df_calibration = edited_calib.copy()

    # 미세조정 버튼
    sel_calib = st.session_state.df_calibration.index[st.session_state.df_calibration['selected'] == True].tolist()
    if sel_calib:
        active_idx = sel_calib[0]
        st.write("🎯 선택된 눈금 미세조정:")
        c1, c2, c3 = st.columns([1, 1, 2])
        with c3:
            move_px = st.number_input("이동 px", min_value=1, value=1, step=1, key="calib_move_step")
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
                # 💡 "Group": "N/A" 추가
                new_row = {"selected": False, "figure_name": st.session_state.figure_name, "X_Label": None, "Group": "N/A", "Value": None, "Type": st.session_state.plot_type, "x_pixel": None, "y_pixel": None}

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
            # 💡 [신규] 줌 슬라이더의 비율을 가져와서 화면에 표시될 이미지 너비 결정
            zoom_factor = st.session_state.get("image_zoom", 100) / 100.0
            display_width = max(100, int(img_rgb.shape[1] * zoom_factor))
            
            # 💡 [신규] 가로형인지 세로형인지 설정값 확인
            is_horizontal = "Horizontal" in st.session_state.get("orientation", "Vertical")
            
            try:
                clicked = streamlit_image_coordinates(Image.fromarray(img_rgb), key="lnp_image_click", width=display_width)

                if clicked is not None:
                    # 💡 [신규] 화면에서 클릭한 좌표를 원래 고해상도 이미지의 실제 픽셀 좌표로 역산
                    scale_ratio = img_rgb.shape[1] / display_width
                    clicked_x = int(round(clicked["x"] * scale_ratio))
                    clicked_y = int(round(clicked["y"] * scale_ratio))
                    
                    # 이미지를 벗어나지 않도록 좌표 제한
                    clicked_x = max(0, min(img_rgb.shape[1] - 1, clicked_x))
                    clicked_y = max(0, min(img_rgb.shape[0] - 1, clicked_y))
                    
                    click_signature = f"{clicked_x}_{clicked_y}"

                    if st.session_state.last_click_signature != click_signature:
                        # 1. 마지막으로 클릭한 좌표 세션에 저장
                        st.session_state.last_click_x = clicked_x
                        st.session_state.last_click_y = clicked_y
                        st.session_state.last_click_signature = click_signature
                        
                        # 2. 타겟 픽셀 결정 (가로형 그래프면 X좌표 거리 기준, 세로형이면 Y좌표 거리 기준)
                        target_pixel = clicked_x if is_horizontal else clicked_y
                        
                        # 3. 노란색 커서 선을 클릭한 위치로 이동
                        st.session_state.cursor_y = target_pixel
                        
                        # 4. 💡 [신규] 표에서 선택한 행이 있다면 즉시 값을 보간 계산하여 표에 기록
                        if selected_row_idx is not None:
                            calc_val = calculate_custom_value(target_pixel)
                            
                            st.session_state.df_extracted.at[selected_row_idx, "Value"] = calc_val
                            st.session_state.df_extracted.at[selected_row_idx, "x_pixel"] = clicked_x
                            st.session_state.df_extracted.at[selected_row_idx, "y_pixel"] = clicked_y
                            
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