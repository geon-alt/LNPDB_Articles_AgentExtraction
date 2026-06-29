import cv2
import numpy as np
import os
import sys
import pandas as pd
from PIL import Image
import json
from pathlib import Path

# --- [경로 설정] ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.append(str(PROJECT_ROOT))

from find_api import find_api_key_file, get_vertexai_client

# Vertex AI 모델 초기화
key_path = find_api_key_file("vertex-490605-8d0be916872a.json")
client = get_vertexai_client(key_path)
MODEL_FLASH = 'gemini-2.5-flash'  # 구역 판별용 초고속 모델
MODEL_PRO = 'gemini-3.1-pro-preview'  # 정밀 수치/라벨 추출용 모델

def imread_korean(path):
    img_array = np.fromfile(path, np.uint8)
    return cv2.imdecode(img_array, cv2.IMREAD_COLOR)

def imwrite_korean(path, img):
    ext = os.path.splitext(path)[1]
    result, encoded_img = cv2.imencode(ext, img)
    if result:
        with open(path, mode='w+b') as f:
            encoded_img.tofile(f)

def merge_overlapping_boxes(boxes, padding=2):
    """겹치거나 인접한 박스들을 하나의 큰 박스로 병합합니다."""
    merged = []
    while boxes:
        box = boxes.pop(0)
        x1, y1, w1, h1 = box

        has_merged = False
        for i, other_box in enumerate(boxes):
            x2, y2, w2, h2 = other_box
            if not (x1 + w1 + padding < x2 or x2 + w2 + padding < x1 or
                    y1 + h1 + padding < y2 or y2 + h2 + padding < y1):
                nx = min(x1, x2)
                ny = min(y1, y2)
                nw = max(x1 + w1, x2 + w2) - nx
                nh = max(y1 + h1, y2 + h2) - ny
                boxes[i] = [nx, ny, nw, nh]
                has_merged = True
                break
        if not has_merged:
            merged.append(box)
    return merged


def extract_point_plot_data(image_path, output_dir='extracted_points_final', tolerance=25, DEBUG=True):
    image = imread_korean(image_path)
    if image is None:
        print(f"이미지를 불러올 수 없습니다: {image_path}")
        return

    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.basename(image_path)
    h_img, w_img = image.shape[:2]
    debug_image = image.copy()

    # =========================================================
    # [Step 1] 축(Axis) 및 눈금(Tick) 물리적 검출
    # =========================================================
    print(f"[{base_name}] 1. 형태학적 축 및 눈금 검출 중...")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary_inv = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (int(w_img * 0.3), 1))
    horiz_lines_img = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel_h)
    row_counts_lines = np.sum(horiz_lines_img, axis=1)

    kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(h_img * 0.3)))
    vert_lines_img = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel_v)
    col_counts_total = np.sum(vert_lines_img, axis=0)

    raw_lines = np.where(row_counts_lines > 0)[0]
    distinct_lines = []
    if len(raw_lines) > 0:
        temp = [raw_lines[0]]
        for i in range(1, len(raw_lines)):
            if raw_lines[i] - raw_lines[i - 1] <= 5:
                temp.append(raw_lines[i])
            else:
                distinct_lines.append(int(np.mean(temp)))
                temp = [raw_lines[i]]
        distinct_lines.append(int(np.mean(temp)))
    else:
        distinct_lines = [int(np.argmax(np.sum(binary_inv, axis=1)))]

    x_axis_y = max(distinct_lines)
    y_axis_x = np.argmax(col_counts_total)

    # --- 눈금(Tick) 검출 로직 ---
    # X축 눈금
    tick_roi_x = binary_inv[x_axis_y + 1: x_axis_y + 10, y_axis_x: w_img]
    col_counts_roi = np.sum(tick_roi_x, axis=0)
    tick_threshold_x = (tick_roi_x.shape[0] * 255) * 0.3
    raw_tick_x = np.where(col_counts_roi > tick_threshold_x)[0] + y_axis_x

    refined_ticks_x = []
    if len(raw_tick_x) > 0:
        temp = [raw_tick_x[0]]
        for i in range(1, len(raw_tick_x)):
            if raw_tick_x[i] - raw_tick_x[i - 1] < 5:
                temp.append(raw_tick_x[i])
            else:
                refined_ticks_x.append(int(np.mean(temp)))
                temp = [raw_tick_x[i]]
        refined_ticks_x.append(int(np.mean(temp)))

    # Y축 눈금 (가장 높은 눈금을 찾기 위함)
    start_x = max(0, y_axis_x - 10)
    tick_roi_y = binary_inv[0: x_axis_y, start_x: y_axis_x]
    row_counts_roi_y = np.sum(tick_roi_y, axis=1)
    tick_threshold_y = 2 * 255
    raw_tick_y = np.where(row_counts_roi_y > tick_threshold_y)[0]

    refined_ticks_y = []
    if len(raw_tick_y) > 0:
        temp = [raw_tick_y[0]]
        for i in range(1, len(raw_tick_y)):
            if raw_tick_y[i] - raw_tick_y[i - 1] < 5:
                temp.append(raw_tick_y[i])
            else:
                refined_ticks_y.append(int(np.mean(temp)))
                temp = [raw_tick_y[i]]
        refined_ticks_y.append(int(np.mean(temp)))

    top_tick_y = min(refined_ticks_y) if refined_ticks_y else None

    # =========================================================
    # [Step 2] Gemini Flash를 활용한 안전한 사분면 마스킹
    # =========================================================
    print("-> 2. Gemini Flash 구역 판별 및 축 마스킹 중...")
    quad_image = image.copy()
    cv2.line(quad_image, (0, x_axis_y), (w_img, x_axis_y), (0, 0, 255), 3)
    cv2.line(quad_image, (y_axis_x, 0), (y_axis_x, h_img), (0, 255, 255), 3)
    cv2.putText(quad_image, "Q1", (y_axis_x + 50, x_axis_y - 50), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 4)
    imwrite_korean(os.path.join(output_dir, f"temp_quad_{base_name}"), quad_image)

    active_quadrants = [1]
    try:
        img_pil = Image.open(os.path.join(output_dir, f"temp_quad_{base_name}"))
        prompt = """
        This image is divided into 4 quadrants (Q1, Q2, Q3, Q4).
        Which quadrants contain the actual graph data (points, bars, error bars)? 
        Ignore quadrants that ONLY contain text labels.
        Return ONLY a JSON array of integers. For example: [1] or [1, 4].
        """
        response = client.models.generate_content(model=MODEL_FLASH, contents=[prompt, img_pil])
        res_text = response.text.strip().replace("`" * 3 + "json", "").replace("`" * 3, "").strip()
        active_quadrants = json.loads(res_text)
    except Exception as e:
        print(f"   [Gemini Flash 오류, 기본값 Q1 사용]: {e}")

    # 데이터 구역 외 전부 하얗게 지우기 (텍스트 방해 제거)
    clean_image = np.full_like(image, 255)
    if 1 in active_quadrants: clean_image[0:x_axis_y, y_axis_x:w_img] = image[0:x_axis_y, y_axis_x:w_img]
    if 2 in active_quadrants: clean_image[0:x_axis_y, 0:y_axis_x] = image[0:x_axis_y, 0:y_axis_x]
    if 3 in active_quadrants: clean_image[x_axis_y:h_img, 0:y_axis_x] = image[x_axis_y:h_img, 0:y_axis_x]
    if 4 in active_quadrants: clean_image[x_axis_y:h_img, y_axis_x:w_img] = image[x_axis_y:h_img, y_axis_x:w_img]

    # 축 선 다리 끊기
    cv2.line(clean_image, (0, x_axis_y), (w_img, x_axis_y), (255, 255, 255), 6)
    cv2.line(clean_image, (y_axis_x, 0), (y_axis_x, h_img), (255, 255, 255), 6)

    # =========================================================
    # [Step 3] 색상 덩어리 추출 및 박스 병합
    # =========================================================
    print("-> 3. 마커 및 에러바 추출 및 병합 중...")
    pixels = clean_image.reshape(-1, 3)
    unique_colors, counts = np.unique(pixels, axis=0, return_counts=True)
    sorted_indices = np.argsort(-counts)

    already_processed = np.zeros(clean_image.shape[:2], dtype=np.uint8)
    candidate_boxes = []

    for idx in sorted_indices:
        if counts[idx] < 2: continue
        color = unique_colors[idx]
        if np.all(color >= 220) or np.all(color <= 20): continue

        lower_bound = np.clip(color.astype(int) - tolerance, 0, 255).astype(np.uint8)
        upper_bound = np.clip(color.astype(int) + tolerance, 0, 255).astype(np.uint8)
        mask = cv2.inRange(clean_image, lower_bound, upper_bound)
        mask = cv2.bitwise_and(mask, cv2.bitwise_not(already_processed))

        if cv2.countNonZero(mask) < 5: continue
        already_processed = cv2.bitwise_or(already_processed, mask)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # [Step 3] contours 반복문 부분
        for cnt in contours:
            # 1. 면적이 유효한 조각만 처리 (cx, cy 정의를 이 안에서 보장)
            if cv2.contourArea(cnt) > 3:
                x, y, w, h = cv2.boundingRect(cnt)
                cx = x + w // 2
                cy = y + h // 2

                # 2. Gemini가 판단한 유효 사분면(active_quadrants) 안에 있는지 검사
                is_valid_area = False
                for q in active_quadrants:
                    if q == 1 and cx > y_axis_x and cy < x_axis_y:
                        is_valid_area = True
                    elif q == 2 and cx < y_axis_x and cy < x_axis_y:
                        is_valid_area = True
                    elif q == 3 and cx < y_axis_x and cy > x_axis_y:
                        is_valid_area = True
                    elif q == 4 and cx > y_axis_x and cy > x_axis_y:
                        is_valid_area = True

                # 3. 데이터 구역(IN)인 경우에만 최종 후보군에 추가
                if is_valid_area:
                    candidate_boxes.append([x, y, w, h])

    # 💡 겹치거나 파편화된 박스들을 하나의 거대한 에러바+마커 그룹으로 병합
    merged_boxes = merge_overlapping_boxes(candidate_boxes, padding=5)

    final_points = []
    for (x, y, w, h) in merged_boxes:
        # 병합된 박스의 정중앙을 해당 마커의 중심 Y(cy)로 간주
        cx = x + w // 2
        cy = y + h // 2
        final_points.append((cx, cy))

        # 디버그 렌더링
        cv2.rectangle(debug_image, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.circle(debug_image, (cx, cy), 3, (0, 0, 255), -1)  # 중심점 빨간색 표시
    if DEBUG:
        final_points = []
        for (x, y, w, h) in merged_boxes:
            cx = x + w // 2
            cy = y + h // 2
            final_points.append((cx, cy))
        if DEBUG:
            cv2.line(debug_image, (0, x_axis_y), (w_img, x_axis_y), (0, 0, 255), 2)
            cv2.line(debug_image, (y_axis_x, 0), (y_axis_x, h_img), (0, 255, 255), 2)
            for tx in refined_ticks_x:
                cv2.line(debug_image, (tx, x_axis_y), (tx, x_axis_y + 10), (255, 0, 0), 2)

            for (bx, by, bw, bh) in merged_boxes:
                cv2.rectangle(debug_image, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)
            for (c_x, c_y) in final_points:
                cv2.circle(debug_image, (c_x, c_y), 3, (0, 0, 255), -1)

            debug_out_path = os.path.join(output_dir, f"debug_final_features_{base_name}")
            imwrite_korean(debug_out_path, debug_image)
        print(f"-> [DEBUG] 모든 피쳐 통합 시각화 이미지 저장 완료: {debug_out_path}")
    print(f"   -> 총 {len(final_points)}개의 독립된 데이터 포인트 병합 완료!")

    # =========================================================
    # [Step 4] Gemini Pro API를 활용한 X/Y축 라벨 및 수치 분석
    # =========================================================
    print("-> 4. Gemini Pro API 라벨/수치 데이터 추출 중...")
    y_max = None
    y_min = 0.0
    gemini_x_labels = []

    try:
        img_pil = Image.open(image_path)
        prompt = """
            Analyze this point/scatter chart image.
            Extract strictly as a JSON object:
            {
              "y_max": (float) the highest numerical value shown on the y-axis ticks,
              "y_min": (float) the lowest numerical value shown on the y-axis ticks (often 0),
              "x_labels": [(string)] a list of all x-axis labels ordered from left to right
            }
            """
        response = client.models.generate_content(model=MODEL_PRO, contents=[prompt, img_pil])
        res_text = response.text.strip()

        # [UI 깨짐 방지용 문자열 조합]
        json_tag = "`" * 3 + "json"
        code_tag = "`" * 3

        if json_tag in res_text:
            res_text = res_text.split(json_tag)[1].split(code_tag)[0].strip()
        elif code_tag in res_text:
            res_text = res_text.replace(code_tag, "").strip()

        data = json.loads(res_text)
        y_max = float(data.get("y_max", 0.0))
        y_min = float(data.get("y_min", 0.0))
        gemini_x_labels = data.get("x_labels", [])
        print(f"   [API 성공] Y축: {y_min} ~ {y_max}")
    except Exception as e:
        print(f"   [API 오류]: {e}")

    # =========================================================
    # [Step 5] 최종 수치 맵핑 및 저장
    # =========================================================
    scale_factor = 0
    if top_tick_y is not None and y_max is not None:
        pixel_distance = x_axis_y - top_tick_y
        if pixel_distance > 0:
            scale_factor = (y_max - y_min) / pixel_distance

    refined_ticks_x.sort()
    x_labels_dict = {}
    for i, tx in enumerate(refined_ticks_x):
        x_labels_dict[tx] = gemini_x_labels[i] if i < len(gemini_x_labels) else f"Tick_{i + 1}"

    final_data = []
    final_points.sort(key=lambda p: p[0])

    for (cx, cy) in final_points:
        nearest_tx = min(refined_ticks_x, key=lambda tx: abs(tx - cx)) if refined_ticks_x else cx
        label = x_labels_dict.get(nearest_tx, "Unknown")

        # 바닥(X축)에서부터 중앙 점(cy)까지의 거리를 계산하여 실제 수치 도출
        actual_val = y_min + ((x_axis_y - cy) * scale_factor)

        final_data.append({
            "X_Label": label,
            "Pixel_Height": cy,  # 컬럼명을 Pixel_Height 또는 Pixel_Value로 통일
            "Actual_Value": round(actual_val, 2),
            "Type": "Point_Normal"  # Bar_Plot과 구조를 맞추기 위해 Type 컬럼 추가
        })

    df = pd.DataFrame(final_data)
    if not df.empty:
        csv_path = os.path.join(output_dir, f"extracted_points_{base_name}.csv")
        df.to_csv(csv_path, index=False)
        print("\n=== [최종 포인트 추출 결과] ===")
        print(df.to_string(index=False))
        print(f"=============================\n-> 데이터 CSV 저장 완료: {csv_path}\n")
    else:
        print("-> 추출된 데이터가 없습니다.")


if __name__ == "__main__":
    test_image_path = './Example_Figs/fig2c.png'
    extract_point_plot_data(test_image_path)