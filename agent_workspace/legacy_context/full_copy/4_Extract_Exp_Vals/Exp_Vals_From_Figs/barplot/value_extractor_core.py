from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import traceback
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

try:
    import cv2
except Exception:  # pragma: no cover - optional runtime dependency check
    cv2 = None

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional runtime dependency check
    Image = None


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ID = "avian-light-492007-c2"
PROJECT_ROOT = None
for _candidate in [CURRENT_DIR, *CURRENT_DIR.parents]:
    if (_candidate / "find_api.py").exists():
        PROJECT_ROOT = _candidate
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

API_IMPORT_ERROR = None
try:
    from find_api import find_api_key_file, get_genai_client

    API_AVAILABLE = True
except Exception as exc:  # pragma: no cover - depends on local API file
    find_api_key_file = None
    get_genai_client = None
    API_AVAILABLE = False
    API_IMPORT_ERROR = str(exc)


EXTRACTED_COLUMNS = [
    "selected",
    "figure_name",
    "X_Label",
    "Group",
    "Value",
    "Type",
    "x_pixel",
    "y_pixel",
]
CALIBRATION_COLUMNS = ["selected", "kind", "Pixel", "Value"]
CALIBRATION_KIND_Y_TICK = "y_tick"
CALIBRATION_KIND_BASELINE = "baseline"
CALIBRATION_KIND_Y_AXIS = "y_axis"
CALIBRATION_KIND_Y_MAX = "y_max"
AXIS_CONTROL_KINDS = {CALIBRATION_KIND_BASELINE, CALIBRATION_KIND_Y_AXIS, CALIBRATION_KIND_Y_MAX}
API_MODE = os.environ.get("GEMINI_API_MODE", "vertex").strip().lower()
DEFAULT_GEMINI_MODEL_PRO = os.environ.get("GEMINI_MODEL_PRO", "gemini-3.1-pro-preview").strip()
DEFAULT_GEMINI_MODEL_FLASH = os.environ.get("GEMINI_MODEL_FLASH", "gemini-2.5-flash").strip()


@dataclass
class AppState:
    image_path: str | None = None
    image_cv: Any = None
    image_pil: Any = None
    uploaded_file_hash: str | None = None
    figure_name: str = ""
    x_labels_input: str = ""
    groups_input: str = ""
    orientation: str = "Vertical (세로형)"
    is_log_scale: bool = False
    plot_type: str = "Unknown"
    baseline_y: int = 200
    y_max_pixel: int = 50
    y_axis_x: int | None = None
    last_click_x: int | None = None
    last_click_y: int | None = None
    df_calibration: pd.DataFrame = field(default_factory=lambda: create_default_calibration_dataframe())
    df_extracted: pd.DataFrame = field(default_factory=lambda: create_empty_extracted_dataframe())


def ensure_dependencies_for_image_processing() -> None:
    if cv2 is None:
        raise ImportError("OpenCV(cv2)가 필요합니다. pip install opencv-python")
    if Image is None:
        raise ImportError("Pillow가 필요합니다. pip install pillow")


def file_to_hash(file_bytes: bytes) -> str:
    return hashlib.md5(file_bytes).hexdigest()


def load_image_from_bytes(file_bytes: bytes):
    ensure_dependencies_for_image_processing()
    np_arr = np.frombuffer(file_bytes, dtype=np.uint8)
    image_cv = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if image_cv is None:
        raise ValueError("OpenCV로 이미지를 디코딩하지 못했습니다.")
    image_pil = Image.open(BytesIO(file_bytes)).convert("RGB")
    return image_cv, image_pil


def load_image_from_path(image_path: str | Path):
    path = Path(image_path)
    data = path.read_bytes()
    return load_image_from_bytes(data)


def cv_to_pil(image_cv):
    ensure_dependencies_for_image_processing()
    return Image.fromarray(cv2.cvtColor(image_cv, cv2.COLOR_BGR2RGB))


def pil_to_cv(image_pil):
    ensure_dependencies_for_image_processing()
    return cv2.cvtColor(np.array(image_pil.convert("RGB")), cv2.COLOR_RGB2BGR)


def create_default_calibration_dataframe() -> pd.DataFrame:
    return ensure_calibration_columns(
        pd.DataFrame(
            [
                {"selected": False, "kind": CALIBRATION_KIND_Y_TICK, "Pixel": 200, "Value": 0.0},
                {"selected": False, "kind": CALIBRATION_KIND_Y_TICK, "Pixel": 50, "Value": 100.0},
                {"selected": False, "kind": CALIBRATION_KIND_BASELINE, "Pixel": 200, "Value": 0.0},
                {"selected": False, "kind": CALIBRATION_KIND_Y_AXIS, "Pixel": pd.NA, "Value": pd.NA},
                {"selected": False, "kind": CALIBRATION_KIND_Y_MAX, "Pixel": 50, "Value": 100.0},
            ]
        )
    )


def create_empty_extracted_dataframe() -> pd.DataFrame:
    return pd.DataFrame(columns=EXTRACTED_COLUMNS)


def to_float_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = str(value).strip()
    if text == "":
        return None
    numeric = pd.to_numeric(pd.Series([text]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return float(numeric)


def is_true(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except Exception:
        pass
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "checked", "selected"}
    return bool(value)


def ensure_extracted_columns(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None:
        df = create_empty_extracted_dataframe()
    df = df.copy()
    for col in EXTRACTED_COLUMNS:
        if col not in df.columns:
            df[col] = False if col == "selected" else None
    return df[EXTRACTED_COLUMNS].reset_index(drop=True)


def ensure_calibration_columns(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None:
        df = create_default_calibration_dataframe()
    df = df.copy()
    for col in CALIBRATION_COLUMNS:
        if col not in df.columns and col == "kind":
            df[col] = CALIBRATION_KIND_Y_TICK
        elif col not in df.columns:
            df[col] = False if col == "selected" else None
    df["kind"] = df["kind"].fillna(CALIBRATION_KIND_Y_TICK).astype(str).str.strip()
    df.loc[df["kind"].eq(""), "kind"] = CALIBRATION_KIND_Y_TICK
    return df[CALIBRATION_COLUMNS].reset_index(drop=True)


def y_tick_calibration_rows(df: pd.DataFrame | None) -> pd.DataFrame:
    df_cal = ensure_calibration_columns(df)
    return df_cal[df_cal["kind"].eq(CALIBRATION_KIND_Y_TICK)].copy()


def append_axis_control_rows(
    calibration_df: pd.DataFrame | None,
    baseline_y=None,
    y_axis_x=None,
    y_max_pixel=None,
    y_max_value=None,
) -> pd.DataFrame:
    df = ensure_calibration_columns(calibration_df)
    df = df[~df["kind"].isin(AXIS_CONTROL_KINDS)].copy()
    rows = [
        {"selected": False, "kind": CALIBRATION_KIND_BASELINE, "Pixel": baseline_y, "Value": 0.0},
        {"selected": False, "kind": CALIBRATION_KIND_Y_AXIS, "Pixel": y_axis_x, "Value": pd.NA},
        {"selected": False, "kind": CALIBRATION_KIND_Y_MAX, "Pixel": y_max_pixel, "Value": y_max_value},
    ]
    return ensure_calibration_columns(pd.concat([df, pd.DataFrame(rows)], ignore_index=True))


def sync_axis_control_rows_from_state(state: AppState) -> AppState:
    state.df_calibration = append_axis_control_rows(
        state.df_calibration,
        baseline_y=state.baseline_y,
        y_axis_x=state.y_axis_x,
        y_max_pixel=state.y_max_pixel,
        y_max_value=None,
    )
    return state


def apply_axis_control_rows_to_state(state: AppState) -> AppState:
    df = ensure_calibration_columns(state.df_calibration)
    for _idx, row in df.iterrows():
        pixel = to_float_or_none(row.get("Pixel"))
        if pixel is None:
            continue
        kind = str(row.get("kind", CALIBRATION_KIND_Y_TICK)).strip()
        if kind == CALIBRATION_KIND_BASELINE:
            state.baseline_y = int(round(pixel))
        elif kind == CALIBRATION_KIND_Y_AXIS:
            state.y_axis_x = int(round(pixel))
        elif kind == CALIBRATION_KIND_Y_MAX:
            state.y_max_pixel = int(round(pixel))
    state.df_calibration = df
    return state


def insert_row_below(df: pd.DataFrame, row_index: int | None, row: dict[str, Any] | None = None) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)
    if row is None:
        row = {col: None for col in df.columns}
        if "selected" in row:
            row["selected"] = False
    new_row = pd.DataFrame([row])
    if row_index is None or row_index < 0 or row_index >= len(df):
        return pd.concat([df, new_row], ignore_index=True)
    return pd.concat([df.iloc[: row_index + 1], new_row, df.iloc[row_index + 1 :]], ignore_index=True)


def delete_rows(df: pd.DataFrame, row_indices: list[int]) -> pd.DataFrame:
    if not row_indices:
        return df.copy().reset_index(drop=True)
    return df.drop(index=[i for i in row_indices if i in df.index]).reset_index(drop=True)


def selected_row_indices(df: pd.DataFrame) -> list[int]:
    if df is None or "selected" not in df.columns:
        return []
    return [int(i) for i, v in df["selected"].items() if bool(v)]


def set_single_selected(df: pd.DataFrame, row_index: int | None) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)
    if "selected" not in df.columns:
        df.insert(0, "selected", False)
    df["selected"] = False
    if row_index is not None and 0 <= row_index < len(df):
        df.at[row_index, "selected"] = True
    return df


def parse_list_input(text: str) -> list[str]:
    if text is None:
        return []
    return [x.strip() for x in str(text).replace("\n", ",").split(",") if x.strip()]


def generate_label_table(
    figure_name: str,
    x_labels_input: str,
    groups_input: str = "",
    plot_type: str = "Manual",
) -> pd.DataFrame:
    labels = parse_list_input(x_labels_input)
    groups = parse_list_input(groups_input) or ["N/A"]
    records = []
    for label in labels:
        for group in groups:
            records.append(
                {
                    "selected": False,
                    "figure_name": figure_name,
                    "X_Label": label,
                    "Group": group,
                    "Value": None,
                    "Type": plot_type,
                    "x_pixel": None,
                    "y_pixel": None,
                }
            )
    return ensure_extracted_columns(pd.DataFrame(records))


def auto_detect_y_limits(image):
    if cv2 is None:
        raise ImportError("OpenCV(cv2)가 필요합니다.")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
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

    roi_left = binary_inv[0:axis_y_0, max(0, y_axis_x - 6) : y_axis_x]
    row_counts = np.sum(roi_left, axis=1)
    tick_rows_relative = np.where(row_counts > 0)[0]
    tick_indices = tick_rows_relative

    axis_y_max = int(min(tick_indices)) if len(tick_indices) > 0 else int(h * 0.1)
    return axis_y_0, axis_y_max, y_axis_x


def auto_detect_all_y_ticks(image):
    if cv2 is None:
        raise ImportError("OpenCV(cv2)가 필요합니다.")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
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

    roi_left = binary_inv[0:axis_y_0, max(0, y_axis_x - 6) : y_axis_x]
    row_counts = np.sum(roi_left, axis=1)
    tick_rows = np.where(row_counts > 0)[0]

    detected_y_pixels = []
    if len(tick_rows) > 0:
        temp_group = [tick_rows[0]]
        for idx in range(1, len(tick_rows)):
            if tick_rows[idx] - tick_rows[idx - 1] <= 5:
                temp_group.append(tick_rows[idx])
            else:
                detected_y_pixels.append(int(np.mean(temp_group)))
                temp_group = [tick_rows[idx]]
        detected_y_pixels.append(int(np.mean(temp_group)))

    return sorted(detected_y_pixels, reverse=True), y_axis_x


def auto_detect_x_ticks(image, y_axis_x, baseline_y):
    if cv2 is None:
        raise ImportError("OpenCV(cv2)가 필요합니다.")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary_inv = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
    h, _w = image.shape[:2]

    scan_top = int(baseline_y) + 1
    scan_bottom = min(h, int(baseline_y) + 10)
    roi = binary_inv[scan_top:scan_bottom, int(y_axis_x) + 5 :]
    col_counts = np.sum(roi, axis=0)

    threshold = max(1, (scan_bottom - scan_top) * 255 * 0.5)
    raw_ticks = [xi for xi, count in enumerate(col_counts) if count > threshold]

    refined_ticks_x = []
    if raw_ticks:
        temp_group = [raw_ticks[0]]
        for idx in range(1, len(raw_ticks)):
            if raw_ticks[idx] - raw_ticks[idx - 1] <= 5:
                temp_group.append(raw_ticks[idx])
            else:
                refined_ticks_x.append(int(y_axis_x) + 5 + int(np.mean(temp_group)))
                temp_group = [raw_ticks[idx]]
        refined_ticks_x.append(int(y_axis_x) + 5 + int(np.mean(temp_group)))
    return refined_ticks_x


def auto_detect_all_x_val_ticks(image):
    if cv2 is None:
        raise ImportError("OpenCV(cv2)가 필요합니다.")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary_inv = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    h, w = image.shape[:2]

    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, int(w * 0.2)), 1))
    horiz_lines = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel_h)
    row_counts_h = np.sum(horiz_lines, axis=1)
    y_indices = np.where(row_counts_h > 0)[0]
    axis_y_0 = int(max(y_indices)) if len(y_indices) > 0 else int(h * 0.9)

    x_line_pixels = np.where(horiz_lines[axis_y_0, :] > 0)[0]
    x_start_px = x_line_pixels[0] if len(x_line_pixels) > 0 else int(w * 0.1)

    roi_bottom = binary_inv[axis_y_0 : min(h, axis_y_0 + 6), x_start_px:]
    col_counts = np.sum(roi_bottom, axis=0)
    tick_cols = np.where(col_counts > 0)[0] + x_start_px

    detected_x_pixels = []
    if len(tick_cols) > 0:
        temp_group = [tick_cols[0]]
        for idx in range(1, len(tick_cols)):
            if tick_cols[idx] - tick_cols[idx - 1] <= 5:
                temp_group.append(tick_cols[idx])
            else:
                detected_x_pixels.append(int(np.mean(temp_group)))
                temp_group = [tick_cols[idx]]
        detected_x_pixels.append(int(np.mean(temp_group)))

    return sorted(detected_x_pixels), axis_y_0


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


def normalize_superscript_text(text: str) -> str:
    superscript_map = str.maketrans(
        {
            "⁰": "0",
            "¹": "1",
            "²": "2",
            "³": "3",
            "⁴": "4",
            "⁵": "5",
            "⁶": "6",
            "⁷": "7",
            "⁸": "8",
            "⁹": "9",
            "⁺": "+",
            "⁻": "-",
            "⁽": "(",
            "⁾": ")",
        }
    )
    return text.translate(superscript_map)


def parse_axis_value_label(raw_value):
    if raw_value is None:
        return None
    if isinstance(raw_value, (int, float, np.integer, np.floating)):
        return float(raw_value)

    s = str(raw_value).strip()
    if not s:
        return None
    s = normalize_superscript_text(s)
    s = s.replace(",", "").replace(" ", "").replace("−", "-")
    s = s.replace("×", "x").replace("*", "x")

    try:
        return float(s)
    except Exception:
        pass

    match = re.fullmatch(r"10(?:\^|\*\*)([-+]?\d+(?:\.\d+)?)", s, flags=re.IGNORECASE)
    if match:
        return 10.0 ** float(match.group(1))

    match = re.fullmatch(
        r"(?:([-+]?\d+(?:\.\d+)?)?)x?10(?:\^|\*\*)([-+]?\d+(?:\.\d+)?)",
        s,
        flags=re.IGNORECASE,
    )
    if match:
        coeff = float(match.group(1)) if match.group(1) not in (None, "") else 1.0
        exp = float(match.group(2))
        return coeff * (10.0**exp)

    numeric_match = re.search(r"[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?", s, flags=re.IGNORECASE)
    if numeric_match and numeric_match.group(0) == s:
        return float(numeric_match.group(0))
    return None


def get_gemini_client():
    if not API_AVAILABLE:
        raise RuntimeError(f"Gemini API 모듈 import 실패: {API_IMPORT_ERROR}")
    api_path = find_api_key_file("vertex.json")
    return get_genai_client(mode=API_MODE, api_path=api_path, project=PROJECT_ID)


def run_gemini_analysis(image_pil, tick_count=None, orientation="Vertical (세로형)"):
    if not API_AVAILABLE:
        return None, f"Gemini API 모듈 import 실패: {API_IMPORT_ERROR}"
    try:
        client = get_gemini_client()
        is_horiz = "Horizontal" in str(orientation)
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
          "value_labels": [1, 10, 100],
          "category_labels": ["label1", "label2", "..."],
          "group_labels": ["Control", "APOE KO"],
          "plot_type": "bar_plot" or "point_plot"
        }}

        value_labels 설명: {val_desc}
        category_labels 설명: {cat_desc}
        {tick_instruction}
        Do not include markdown fences.
        """
        response = client.models.generate_content(model=DEFAULT_GEMINI_MODEL_PRO, contents=[prompt, image_pil])
        text = extract_text_from_genai_response(response)
        return parse_json_from_response_text(text), None
    except Exception as exc:
        return None, f"Gemini 분석 실패: {exc}"


def _emit_status(status_target: Any, message: str) -> None:
    if status_target is None:
        return
    if callable(status_target):
        status_target(message)
        return
    text_method = getattr(status_target, "text", None)
    if callable(text_method):
        text_method(message)


def autonomous_y_finder(
    image_cv,
    target_x,
    baseline_y,
    y_max_pixel,
    client=None,
    status_placeholder=None,
    x_label="",
    group_name="",
    max_iterations=4,
):
    if cv2 is None or Image is None:
        raise ImportError("OpenCV와 Pillow가 필요합니다.")
    if client is None:
        client = get_gemini_client()

    _emit_status(status_placeholder, f"[{x_label} - {group_name}] 1단계: Pro 모델 초기 Y 추정 중...")
    img_p1 = image_cv.copy()
    cv2.line(img_p1, (int(target_x), int(baseline_y)), (int(target_x), max(0, int(y_max_pixel) - 30)), (0, 255, 255), 2)
    pil_p1 = cv_to_pil(img_p1)
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
        res1 = client.models.generate_content(model=DEFAULT_GEMINI_MODEL_PRO, contents=[prompt_p1, pil_p1])
        data1 = parse_json_from_response_text(extract_text_from_genai_response(res1))
        current_y = int(data1.get("estimated_y", baseline_y * 0.8))
    except Exception:
        current_y = int(baseline_y * 0.8)

    for i in range(int(max_iterations)):
        _emit_status(status_placeholder, f"[{x_label} - {group_name}] 2단계: Flash 보정 중... ({i + 1}, Y={current_y})")
        img_p2 = image_cv.copy()
        cv2.line(img_p2, (int(target_x) - 20, current_y), (int(target_x) + 20, current_y), (0, 0, 255), 2)
        pil_p2 = cv_to_pil(img_p2)
        prompt_p2 = f"""
        Analyze this chart and return ONLY valid JSON.
        빨간색 가로선이 '{x_label}' 항목의 '{group_name}' 색상 막대 최상단 평면에 일치하는지 평가하세요.
        이미지 좌표계는 맨 위가 0, 아래로 갈수록 커집니다.
        {{"status": "PERFECT" or "ADJUST", "move_pixels": int}}
        """
        try:
            res2 = client.models.generate_content(model=DEFAULT_GEMINI_MODEL_FLASH, contents=[prompt_p2, pil_p2])
            data2 = parse_json_from_response_text(extract_text_from_genai_response(res2))
            move_pixels = int(data2.get("move_pixels", 0))
            if data2.get("status") == "PERFECT" or move_pixels == 0:
                break
            current_y += move_pixels
            current_y = max(0, min(current_y, image_cv.shape[0] - 1))
        except Exception:
            break

    _emit_status(status_placeholder, f"[{x_label} - {group_name}] 3단계: Pro 최종 검증 중...")
    img_p3 = image_cv.copy()
    cv2.line(img_p3, (int(target_x) - 20, current_y), (int(target_x) + 20, current_y), (0, 0, 255), 2)
    pil_p3 = cv_to_pil(img_p3)
    prompt_p3 = f"""
    Analyze this chart and return ONLY valid JSON.
    빨간색 가로선이 '{group_name}' 막대의 최상단 평면에 완벽하게 일치하는지 최종 확인하세요.
    {{"status": "PERFECT" or "ADJUST", "move_pixels": int}}
    """
    try:
        res3 = client.models.generate_content(model=DEFAULT_GEMINI_MODEL_PRO, contents=[prompt_p3, pil_p3])
        data3 = parse_json_from_response_text(extract_text_from_genai_response(res3))
        current_y += int(data3.get("move_pixels", 0))
        current_y = max(0, min(current_y, image_cv.shape[0] - 1))
    except Exception:
        pass

    _emit_status(status_placeholder, f"[{x_label} - {group_name}] 추출 완료: Y={current_y}")
    return current_y


def calculate_custom_value(clicked_pixel: float, calibration_df: pd.DataFrame | None = None, is_log_scale: bool = False):
    df_cal = y_tick_calibration_rows(calibration_df).dropna(subset=["Pixel", "Value"]).copy()
    if len(df_cal) < 2:
        return 0.0
    df_cal["Pixel"] = pd.to_numeric(df_cal["Pixel"], errors="coerce")
    df_cal["Value"] = pd.to_numeric(df_cal["Value"], errors="coerce")
    df_cal = df_cal.dropna(subset=["Pixel", "Value"]).sort_values("Value").reset_index(drop=True)
    if len(df_cal) < 2:
        return 0.0

    pixels = df_cal["Pixel"].to_numpy(dtype=float)
    values = df_cal["Value"].to_numpy(dtype=float)

    def to_space(value):
        return np.log10(value) if is_log_scale and value > 0 else float(value)

    def from_space(value):
        return 10**value if is_log_scale else float(value)

    val_space = np.array([to_space(v) for v in values], dtype=float)
    distances = np.abs(pixels - float(clicked_pixel))
    idx1, idx2 = np.argsort(distances)[:2]

    p1, p2 = pixels[idx1], pixels[idx2]
    v1, v2 = val_space[idx1], val_space[idx2]
    if p1 == p2:
        return round(from_space(v1), 4)
    ratio = (float(clicked_pixel) - p1) / (p2 - p1)
    calc_val_space = v1 + ratio * (v2 - v1)
    return round(from_space(calc_val_space), 4)


def recalculate_values(
    df_extracted: pd.DataFrame,
    df_calibration: pd.DataFrame,
    orientation: str = "Vertical (세로형)",
    is_log_scale: bool = False,
) -> pd.DataFrame:
    df = ensure_extracted_columns(df_extracted)
    pixel_col = "x_pixel" if "Horizontal" in str(orientation) else "y_pixel"
    for idx, row in df.iterrows():
        pixel = pd.to_numeric(pd.Series([row.get(pixel_col)]), errors="coerce").iloc[0]
        if pd.isna(pixel):
            continue
        df.at[idx, "Value"] = calculate_custom_value(float(pixel), df_calibration, is_log_scale)
    return df


def apply_click_to_row(
    df_extracted: pd.DataFrame,
    row_index: int,
    x_pixel: int,
    y_pixel: int,
    df_calibration: pd.DataFrame,
    orientation: str = "Vertical (세로형)",
    is_log_scale: bool = False,
) -> tuple[pd.DataFrame, float]:
    df = ensure_extracted_columns(df_extracted)
    if row_index < 0 or row_index >= len(df):
        raise IndexError("선택된 행이 없습니다.")
    df.at[row_index, "x_pixel"] = int(x_pixel)
    df.at[row_index, "y_pixel"] = int(y_pixel)
    value_pixel = x_pixel if "Horizontal" in str(orientation) else y_pixel
    value = calculate_custom_value(value_pixel, df_calibration, is_log_scale)
    df.at[row_index, "Value"] = value
    return df, value


def build_first_pass_tables(
    data: dict[str, Any],
    all_value_pixels: list[int],
    figure_name: str,
    baseline_y=None,
    y_axis_x=None,
    y_max_pixel=None,
) -> tuple[pd.DataFrame, pd.DataFrame, str, str, str]:
    plot_type = str(data.get("plot_type", "Unknown"))
    raw_values = data.get("value_labels", [])
    parsed_values = []
    for idx in range(len(all_value_pixels)):
        parsed_values.append(parse_axis_value_label(raw_values[idx]) if idx < len(raw_values) else None)
    calibration_df = pd.DataFrame(
        {
            "selected": [False] * len(all_value_pixels),
            "kind": [CALIBRATION_KIND_Y_TICK] * len(all_value_pixels),
            "Pixel": all_value_pixels,
            "Value": parsed_values,
        }
    )
    y_max_value = parsed_values[-1] if parsed_values else None
    calibration_df = append_axis_control_rows(
        calibration_df,
        baseline_y=baseline_y,
        y_axis_x=y_axis_x,
        y_max_pixel=y_max_pixel,
        y_max_value=y_max_value,
    )
    labels = [str(x).strip() for x in data.get("category_labels", []) if str(x).strip()]
    groups = [str(g).strip() for g in data.get("group_labels", []) if str(g).strip()]
    extracted_df = generate_label_table(figure_name, ", ".join(labels), ", ".join(groups), plot_type)
    return calibration_df, extracted_df, ", ".join(labels), ", ".join(groups), plot_type


def run_first_pass_analysis(state: AppState) -> AppState:
    if state.image_cv is None or state.image_pil is None:
        raise ValueError("이미지를 먼저 열어야 합니다.")
    is_horizontal = "Horizontal" in str(state.orientation)
    if is_horizontal:
        all_value_pixels, axis_y_0 = auto_detect_all_x_val_ticks(state.image_cv)
        state.baseline_y = int(axis_y_0)
    else:
        all_value_pixels, y_axis_x = auto_detect_all_y_ticks(state.image_cv)
        state.y_axis_x = int(y_axis_x)
        state.baseline_y = int(all_value_pixels[0]) if all_value_pixels else int(state.image_cv.shape[0] * 0.9)

    data, err = run_gemini_analysis(state.image_pil, tick_count=len(all_value_pixels), orientation=state.orientation)
    if err:
        raise RuntimeError(err)
    if not data:
        raise RuntimeError("Gemini 분석 결과가 비어 있습니다.")

    if len(all_value_pixels) >= 2:
        state.y_max_pixel = int(all_value_pixels[-1] if not is_horizontal else all_value_pixels[-1])
    calibration_df, extracted_df, labels, groups, plot_type = build_first_pass_tables(
        data,
        all_value_pixels,
        state.figure_name,
        baseline_y=state.baseline_y,
        y_axis_x=state.y_axis_x,
        y_max_pixel=state.y_max_pixel,
    )
    state.df_calibration = calibration_df
    state.df_extracted = extracted_df
    state.x_labels_input = labels
    state.groups_input = groups
    state.plot_type = plot_type
    return state


def run_autonomous_extraction(state: AppState, status_callback: Callable[[str], None] | None = None) -> AppState:
    if state.image_cv is None:
        raise ValueError("이미지를 먼저 열어야 합니다.")
    if not API_AVAILABLE:
        raise RuntimeError(f"Gemini API 모듈 import 실패: {API_IMPORT_ERROR}")
    client = get_gemini_client()
    df = ensure_extracted_columns(state.df_extracted)
    if df.empty:
        raise ValueError("추출 표가 비어 있습니다.")

    y0, y_max_pixel, y_axis_x = auto_detect_y_limits(state.image_cv)
    state.baseline_y = int(y0)
    state.y_max_pixel = int(y_max_pixel)
    state.y_axis_x = int(y_axis_x)
    x_centers = auto_detect_x_ticks(state.image_cv, y_axis_x, state.baseline_y)
    if not x_centers:
        raise RuntimeError("X축 눈금 또는 막대 중심을 감지하지 못했습니다.")

    unique_labels = [x for x in df["X_Label"].dropna().unique().tolist()]
    label_to_x = {label: x_centers[i] for i, label in enumerate(unique_labels) if i < len(x_centers)}

    total = len(df)
    for pos, (idx, row) in enumerate(df.iterrows(), start=1):
        x_label = row.get("X_Label")
        group_name = row.get("Group", "N/A")
        target_x = label_to_x.get(x_label)
        if target_x is None:
            continue
        if status_callback:
            status_callback(f"{pos}/{total}: {x_label} / {group_name}")
        final_y = autonomous_y_finder(
            state.image_cv,
            target_x,
            state.baseline_y,
            state.y_max_pixel,
            client=client,
            status_placeholder=status_callback,
            x_label=x_label,
            group_name=group_name,
        )
        df.at[idx, "x_pixel"] = int(target_x)
        df.at[idx, "y_pixel"] = int(final_y)
        df.at[idx, "Value"] = calculate_custom_value(final_y, state.df_calibration, state.is_log_scale)
    state.df_extracted = df
    return state


def save_extracted_csv(df_extracted: pd.DataFrame, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_extracted_columns(df_extracted).to_csv(path, index=False)
    return path


def state_from_image_path(image_path: str | Path) -> AppState:
    image_cv, image_pil = load_image_from_path(image_path)
    path = Path(image_path)
    state = AppState(
        image_path=str(path),
        image_cv=image_cv,
        image_pil=image_pil,
        uploaded_file_hash=file_to_hash(path.read_bytes()),
        df_calibration=create_default_calibration_dataframe(),
        df_extracted=create_empty_extracted_dataframe(),
    )
    return sync_axis_control_rows_from_state(state)


def traceback_to_string(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
