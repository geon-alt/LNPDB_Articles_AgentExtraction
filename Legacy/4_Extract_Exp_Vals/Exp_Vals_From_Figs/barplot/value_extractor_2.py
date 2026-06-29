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

# value_extractor.py가 하위 폴더로 이동하더라도
# 상위 폴더들을 훑으면서 find_api.py가 있는 프로젝트 루트를 찾음
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
# 자동 축 감지
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

    if len(tick_indices) > 0:
        axis_y_max = int(min(tick_indices)) + start_y
    else:
        axis_y_max = int(h * 0.1)

    return axis_y_0, axis_y_max


# =========================
# Gemini 분석
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
        res = client.models.generate_content(
            model="gemini-3.1-pro-preview",
            contents=[prompt, image_pil]
        )

        text = res.text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        return data, None

    except Exception as e:
        return None, f"Gemini 분석 실패: {e}"


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
    if st.session_state.image_cv is None:
        return
    h = st.session_state.image_cv.shape[0]
    st.session_state.cursor_y = max(0, min(h - 1, int(clicked_y)))

def move_cursor(dy: int):
    ensure_cursor_y()
    h = st.session_state.image_cv.shape[0]
    new_y = int(st.session_state.cursor_y) + int(dy)
    new_y = max(0, min(h - 1, new_y))
    st.session_state.cursor_y = new_y


def apply_cursor_to_selected_row(selected_row_idx: int):
    ensure_cursor_y()

    if selected_row_idx is None:
        return False, "먼저 데이터 매칭 표에서 행을 선택하세요."

    if not (0 <= selected_row_idx < len(st.session_state.df_extracted)):
        return False, "선택된 행 인덱스가 유효하지 않습니다."

    clicked_x = st.session_state.last_click_x if st.session_state.last_click_x is not None else 0
    clicked_y = int(st.session_state.cursor_y)

    value = calculate_value_from_click(clicked_y)
    st.session_state.df_extracted.at[selected_row_idx, "Value"] = value
    st.session_state.df_extracted.at[selected_row_idx, "x_pixel"] = int(clicked_x)
    st.session_state.df_extracted.at[selected_row_idx, "y_pixel"] = int(clicked_y)

    return True, value
# =========================
# 클릭값을 선택 행에 반영
# =========================
def apply_click_to_selected_row(selected_row_idx: int, clicked_x: int, clicked_y: int):
    if selected_row_idx is None:
        return False, "먼저 데이터 매칭 표에서 행을 선택하세요."

    if not (0 <= selected_row_idx < len(st.session_state.df_extracted)):
        return False, "선택된 행 인덱스가 유효하지 않습니다."

    click_signature = f"{selected_row_idx}_{clicked_x}_{clicked_y}"
    if st.session_state.last_applied_click_signature == click_signature:
        return False, "이미 같은 클릭이 반영되었습니다."

    value = calculate_value_from_click(clicked_y)
    st.session_state.df_extracted.at[selected_row_idx, "Value"] = value
    st.session_state.df_extracted.at[selected_row_idx, "x_pixel"] = int(clicked_x)
    st.session_state.df_extracted.at[selected_row_idx, "y_pixel"] = int(clicked_y)
    st.session_state.last_applied_click_signature = click_signature
    return True, value


# =========================
# 표시용 이미지 생성
# =========================
def build_display_image(selected_row_idx=None):
    if st.session_state.image_cv is None:
        return None

    display_img = st.session_state.image_cv.copy()
    h, w = display_img.shape[:2]

    axis_y = int(st.session_state.axis_y)
    y_max_pixel = int(st.session_state.y_max_pixel)
    baseline_y = int(st.session_state.baseline_y)

    axis_y = max(0, min(h - 1, axis_y))
    y_max_pixel = max(0, min(h - 1, y_max_pixel))
    baseline_y = max(0, min(h - 1, baseline_y))

    cv2.line(display_img, (0, axis_y), (w, axis_y), (0, 0, 255), 2)
    cv2.line(display_img, (0, y_max_pixel), (w, y_max_pixel), (255, 0, 0), 2)
    cv2.line(display_img, (0, baseline_y), (w, baseline_y), (255, 0, 255), 2)

    # 현재 선택용 움직이는 커서 바
    ensure_cursor_y()
    cursor_y = max(0, min(h - 1, int(st.session_state.cursor_y)))

    overlay = display_img.copy()
    cv2.line(overlay, (0, cursor_y), (w, cursor_y), (0, 255, 255), 2)
    display_img = cv2.addWeighted(overlay, 0.35, display_img, 0.65, 0)

    # 좌측 끝에 작은 표시
    cv2.rectangle(display_img, (0, max(0, cursor_y - 4)), (18, min(h - 1, cursor_y + 4)), (0, 255, 255), -1)

    for idx, row in st.session_state.df_extracted.iterrows():
        if pd.notna(row.get("x_pixel")) and pd.notna(row.get("y_pixel")):
            px_x, px_y = int(row["x_pixel"]), int(row["y_pixel"])
            px_x = max(0, min(w - 1, px_x))
            px_y = max(0, min(h - 1, px_y))

            if idx == selected_row_idx:
                color = (0, 255, 255)
                radius = 4
                alpha = 0.40
            else:
                color = (0, 255, 0)
                radius = 2
                alpha = 0.22

            overlay = display_img.copy()
            cv2.circle(overlay, (px_x, px_y), radius, color, -1)
            display_img = cv2.addWeighted(overlay, alpha, display_img, 1 - alpha, 0)

    return cv2.cvtColor(display_img, cv2.COLOR_BGR2RGB)


# =========================
# 업로드 처리
# =========================
def handle_upload(uploaded_file):
    if uploaded_file is None:
        return

    file_bytes = uploaded_file.getvalue()
    file_hash = file_to_hash(file_bytes)

    if st.session_state.uploaded_file_hash == file_hash:
        return

    image_cv, image_pil = load_image_from_bytes(file_bytes)

    st.session_state.uploaded_file_hash = file_hash
    st.session_state.uploaded_file_name = uploaded_file.name
    st.session_state.uploaded_bytes = file_bytes
    st.session_state.image_cv = image_cv
    st.session_state.image_pil = image_pil

    reset_analysis_state_preserve_image()

    st.session_state.cursor_y = int(st.session_state.baseline_y)


# =========================
# UI
# =========================
st.title("📊 LNPDB Plot Extractor")

with st.sidebar:
    st.header("1. 이미지 업로드")
    uploaded_file = st.file_uploader("이미지 업로드", type=["png", "jpg", "jpeg"])
    handle_upload(uploaded_file)

    if st.session_state.image_cv is not None:
        st.caption(f"현재 파일: {st.session_state.uploaded_file_name}")

        if st.button("🤖 AI 자동 분석 및 표 생성", use_container_width=True):
            with st.spinner("자동 분석 중..."):
                try:
                    detected_y0, detected_ymax_px = auto_detect_y_limits(st.session_state.image_cv)

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

                        labels = data.get("x_labels", [])
                        if not isinstance(labels, list):
                            labels = []
                        labels = [str(x).strip() for x in labels if str(x).strip()]

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
                        st.success("자동 분석 완료")

                except Exception as e:
                    st.error(f"자동 분석 중 오류 발생: {e}")

    st.divider()
    st.header("2. 수동 설정")

    st.session_state.axis_y = st.number_input(
        "기준 X축(0점) 높이(px)", min_value=0, value=int(st.session_state.input_axis_y), step=1
    )

    st.session_state.y_max_pixel = st.number_input(
        "Y Max 눈금 높이(px)", min_value=0, value=int(st.session_state.input_y_max_pixel), step=1
    )

    st.session_state.baseline_y = st.number_input(
        "측정 시작점 높이(px)", min_value=0, value=int(st.session_state.input_baseline_y), step=1
    )

    st.session_state.y_max = st.number_input("Y Max", value=float(st.session_state.y_max), step=0.1)
    st.session_state.y_min = st.number_input("Y Min", value=float(st.session_state.y_min), step=0.1)
    st.divider()

    st.session_state.figure_name = st.text_input(
        "Figure name",
        value=st.session_state.figure_name,
        placeholder="예: Figure 2B"
    )

    st.header("3. 라벨 수동 입력/수정")


    x_labels_text = st.text_area(
        "X labels (콤마로 구분)",
        value=st.session_state.x_labels_input,
        height=120,
    )

    if st.button("라벨 표 생성/갱신", use_container_width=True):
        labels = [x.strip() for x in x_labels_text.split(",") if x.strip()]
        st.session_state.x_labels_input = ", ".join(labels)
        st.session_state.df_extracted = pd.DataFrame({
            "selected": [False] * len(labels),
            "figure_name": [st.session_state.figure_name] * len(labels),
            "X_Label": labels,
            "Value": [None] * len(labels),
            "Type": [st.session_state.plot_type] * len(labels),
            "x_pixel": [None] * len(labels),
            "y_pixel": [None] * len(labels),
        })
        st.success("표를 갱신했습니다.")

    st.divider()
    st.header("4. 수동 좌표 입력(백업용)")

    click_x = st.number_input("클릭 X", min_value=0, value=int(st.session_state.last_click_x or 0), step=1)
    click_y = st.number_input("클릭 Y", min_value=0, value=int(st.session_state.last_click_y or 0), step=1)

    if st.button("현재 좌표 저장", use_container_width=True):
        st.session_state.last_click_x = int(click_x)
        st.session_state.last_click_y = int(click_y)
        st.success(f"좌표 저장됨: x={click_x}, y={click_y}")


# =========================
# 메인 화면
# =========================
if st.session_state.image_cv is not None:
    col_table, col_img = st.columns([0.9, 1.8], gap="large")

    with col_table:
        st.subheader("5. 데이터 매칭 표")

        # 1) 컬럼 구조 보정: editor 전에 먼저 수행
        required_cols = ["selected", "figure_name", "X_Label", "Value", "Type", "x_pixel", "y_pixel"]

        if "df_extracted" not in st.session_state or st.session_state.df_extracted is None:
            st.session_state.df_extracted = pd.DataFrame(columns=required_cols)

        for col in required_cols:
            if col not in st.session_state.df_extracted.columns:
                if col == "selected":
                    st.session_state.df_extracted[col] = False
                else:
                    st.session_state.df_extracted[col] = None

        # 컬럼 순서 강제 + index 정리
        st.session_state.df_extracted = (
            st.session_state.df_extracted[required_cols]
            .reset_index(drop=True)
        )

        # 2) 버튼
        btn_col1, btn_col2 = st.columns(2)

        with btn_col1:
            if st.button("행 추가", use_container_width=True):
                new_row = {
                    "selected": False,
                    "figure_name": st.session_state.figure_name if st.session_state.figure_name else None,
                    "X_Label": None,
                    "Value": None,
                    "Type": st.session_state.plot_type if st.session_state.plot_type else "bar_plot",
                    "x_pixel": None,
                    "y_pixel": None,
                }
                st.session_state.df_extracted = pd.concat(
                    [st.session_state.df_extracted, pd.DataFrame([new_row])],
                    ignore_index=True
                ).reset_index(drop=True)
                st.rerun()

        with btn_col2:
            if st.button("선택 행 삭제", use_container_width=True):
                df = st.session_state.df_extracted.copy()
                df = df[df["selected"] != True].reset_index(drop=True)
                st.session_state.df_extracted = df
                st.rerun()

        # 3) editor는 한 번만
        edited_df = st.data_editor(
            st.session_state.df_extracted,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "selected": st.column_config.CheckboxColumn(
                    "선택",
                    help="현재 작업할 행 선택",
                    default=False,
                ),
                "figure_name": st.column_config.TextColumn(
                    "figure_name",
                    help="Figure 이름",
                ),
                "X_Label": st.column_config.TextColumn(
                    "X_Label",
                    help="막대/항목 이름",
                ),
                "Value": st.column_config.NumberColumn(
                    "Value",
                    help="추출 값",
                    format="%.4f",
                ),
                "Type": st.column_config.SelectboxColumn(
                    "Type",
                    options=["bar_plot", "point_plot", "line_plot", "scatter", "Unknown"],
                ),
                "x_pixel": st.column_config.NumberColumn(
                    "x_pixel",
                    help="기록용 x 좌표",
                    disabled=True,
                ),
                "y_pixel": st.column_config.NumberColumn(
                    "y_pixel",
                    help="기록용 y 좌표",
                    disabled=True,
                ),
            },
            disabled=["x_pixel", "y_pixel"],
            key="df_editor_main",
        )

        st.session_state.df_extracted = edited_df.copy().reset_index(drop=True)

        # 4) 선택 행 계산도 한 번만
        selected_indices = st.session_state.df_extracted.index[
            st.session_state.df_extracted["selected"] == True
            ].tolist()

        selected_row_idx = None
        if len(selected_indices) == 0:
            st.info("먼저 데이터 매칭 표에서 행을 하나 선택하세요.")
        elif len(selected_indices) == 1:
            selected_row_idx = selected_indices[0]
            target_label = st.session_state.df_extracted.iloc[selected_row_idx]["X_Label"]
            st.success(f"선택된 행: {target_label}")
        else:
            selected_row_idx = selected_indices[0]
            target_label = st.session_state.df_extracted.iloc[selected_row_idx]["X_Label"]
            st.warning("여러 행이 선택되어 있어 첫 번째 선택 행만 사용합니다.")
            st.success(f"현재 사용 행: {target_label}")

    with col_img:
        st.subheader("6. 그래프 미리보기")

        img_rgb = build_display_image(selected_row_idx)

        if img_rgb is not None:
            display_width = min(img_rgb.shape[1] * 2, 1800)

            clicked = streamlit_image_coordinates(
                Image.fromarray(img_rgb),
                key="lnp_image_click",
                width=display_width,
            )

            if clicked is not None:
                scale_x = img_rgb.shape[1] / display_width
                scale_y = scale_x

                clicked_x = int(round(clicked["x"] * scale_x))
                clicked_y = int(round(clicked["y"] * scale_y))

                clicked_x = max(0, min(img_rgb.shape[1] - 1, clicked_x))
                clicked_y = max(0, min(img_rgb.shape[0] - 1, clicked_y))

                click_signature = f"{clicked_x}_{clicked_y}"

                if st.session_state.last_click_signature != click_signature:
                    st.session_state.last_click_x = clicked_x
                    st.session_state.last_click_y = clicked_y
                    st.session_state.last_click_signature = click_signature

                    # 클릭하면 바로 값 반영하지 말고, 커서 바 위치만 바꿈
                    set_cursor_from_click(clicked_y)
                    st.rerun()

            st.caption(
                "사용 순서: 표에서 행 선택 → 이미지 클릭해서 bar 위치 대략 지정 → ▲/▼ 또는 y값으로 미세 조정 → '현재 값 적용' 클릭"
            )
            st.divider()

            # 클릭 정보 표시
            if st.session_state.last_click_x is not None and st.session_state.last_click_y is not None:
                st.write(
                    f"최근 클릭 좌표: x={st.session_state.last_click_x}, y={st.session_state.last_click_y}"
                )
                try:
                    preview_value = calculate_value_from_click(int(st.session_state.cursor_y))
                    st.write(f"현재 bar 기준 계산값: {preview_value}")
                except Exception as e:
                    st.warning(f"값 미리보기 실패: {e}")
            else:
                st.info("그래프를 한 번 클릭하면 bar 위치를 잡을 수 있습니다.")

            if selected_row_idx is not None:
                st.session_state.selected_row_idx_memory = selected_row_idx
            else:
                st.session_state.selected_row_idx_memory = None

            ensure_cursor_y()

            # 상단 보조 버튼
            top_btn1, top_btn2 = st.columns(2)

            with top_btn1:
                if st.button("선택 해제", use_container_width=True):
                    if "df_extracted" in st.session_state and len(st.session_state.df_extracted) > 0:
                        st.session_state.df_extracted["selected"] = False
                    st.rerun()

            with top_btn2:
                if st.button("현재 fig 이름으로 전체 적용", use_container_width=True):
                    if "df_extracted" in st.session_state and len(st.session_state.df_extracted) > 0:
                        st.session_state.df_extracted["figure_name"] = st.session_state.figure_name
                    st.rerun()

            st.markdown("### 6-1. 선택 바 이동")

            c1, c2, c3, c4 = st.columns([1, 1, 2, 2])

            with c1:
                if st.button("▲ 위", use_container_width=True):
                    move_cursor(-int(st.session_state.cursor_step))
                    st.rerun()

            with c2:
                if st.button("▼ 아래", use_container_width=True):
                    move_cursor(int(st.session_state.cursor_step))
                    st.rerun()

            with c3:
                st.number_input(
                    "이동 px",
                    min_value=1,
                    step=1,
                    key="cursor_step",
                )

            with c4:
                st.number_input(
                    "현재 bar y",
                    min_value=0,
                    max_value=int(st.session_state.image_cv.shape[0] - 1),
                    step=1,
                    key="cursor_y",
                )

            try:
                preview_value = calculate_value_from_click(int(st.session_state.cursor_y))
                st.write(f"현재 바 기준 계산값: {preview_value}")
            except Exception as e:
                st.warning(f"값 미리보기 실패: {e}")

            if selected_row_idx is not None:
                if st.button("현재 값 적용", use_container_width=True):
                    ok, result = apply_cursor_to_selected_row(selected_row_idx)
                    if ok:
                        st.success(f"반영 완료: Value={result}")
                        st.rerun()
                    else:
                        st.warning(result)
            else:
                st.info("값을 반영하려면 표에서 행을 하나 선택하세요.")
        else:
            st.warning("표시할 이미지가 없습니다.")


if __name__ == "__main__":
    import sys
    from streamlit.web import cli
    from streamlit import runtime

    if not runtime.exists():
        sys.argv = ["streamlit", "run", __file__]
        sys.exit(cli.main())

# python -m streamlit run 경로/value_extractor_image_coordinates.py