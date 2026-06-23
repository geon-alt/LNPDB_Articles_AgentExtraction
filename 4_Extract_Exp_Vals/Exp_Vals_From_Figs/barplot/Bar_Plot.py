import cv2
import numpy as np
import os
import sys
import pandas as pd
from PIL import Image
import json
from pathlib import Path
from collections import Counter

# --- [경로 설정] 프로젝트 최상위의 find_api 활용 ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.append(str(PROJECT_ROOT))

from find_api import find_api_key_file, get_vertexai_client

# 1. Vertex AI 초기화
key_path = find_api_key_file("vertex-490605-8d0be916872a.json")
client = get_vertexai_client(key_path)
MODEL_FLASH = 'gemini-2.5-flash'
MODEL_PRO = 'gemini-3.1-pro-preview'

def imread_korean(path):
    img_array = np.fromfile(path, np.uint8)
    return cv2.imdecode(img_array, cv2.IMREAD_COLOR)

def imwrite_korean(path, img):
    ext = os.path.splitext(path)[1]
    result, encoded_img = cv2.imencode(ext, img)
    if result:
        with open(path, mode='w+b') as f:
            encoded_img.tofile(f)

def merge_overlapping_boxes(boxes, padding=5):
    merged = []
    while boxes:
        box = boxes.pop(0)
        x1, y1, w1, h1, color1 = box
        has_merged = False
        for i, other_box in enumerate(boxes):
            x2, y2, w2, h2, color2 = other_box
            if not (x1 + w1 + padding < x2 or x2 + w2 + padding < x1 or
                    y1 + h1 + padding < y2 or y2 + h2 + padding < y1):
                nx, ny = min(x1, x2), min(y1, y2)
                nw, nh = max(x1 + w1, x2 + w2) - nx, max(y1 + h1, y2 + h2) - ny
                boxes[i] = [nx, ny, nw, nh, color1]
                has_merged = True
                break
        if not has_merged: merged.append(box)
    return merged


def extract_bars_with_ocr_and_merge(image_path, output_dir='extracted_bars_final', tolerance=15, con_tol=5, DEBUG=True):
    image = imread_korean(image_path)
    if image is None: return
    os.makedirs(output_dir, exist_ok=True)
    debug_image = image.copy()
    base_name = os.path.basename(image_path)
    h_img, w_img = image.shape[:2]

    # [Step 0] 변수 초기화
    top_tick_y = None

    # [Step 1] 축 검출
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary_inv = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (int(w_img * 0.3), 1))
    row_counts_lines = np.sum(cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, kernel_h), axis=1)
    x_axis_y = max(np.where(row_counts_lines > 0)[0]) if np.any(row_counts_lines > 0) else int(h_img * 0.9)
    y_axis_x = np.argmax(np.sum(
        cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(h_img * 0.3)))),
        axis=0))

    # [Step 2] Gemini 사분면 마스킹
    print(f"[{base_name}] 2. Gemini Flash 구역 판별 중...")
    quad_preview = image.copy()
    cv2.line(quad_preview, (0, x_axis_y), (w_img, x_axis_y), (0, 0, 255), 3)
    cv2.line(quad_preview, (y_axis_x, 0), (y_axis_x, h_img), (0, 255, 255), 3)
    temp_quad_path = os.path.join(output_dir, f"temp_quad_{base_name}")
    imwrite_korean(temp_quad_path, quad_preview)
    active_quadrants = [1]
    try:
        img_pil = Image.open(temp_quad_path)
        prompt = "Which quadrants (Q1, Q2, Q3, Q4) contain bar graph data? Return JSON array of ints only."
        response = client.models.generate_content(model=MODEL_FLASH, contents=[prompt, img_pil])
        active_quadrants = json.loads(response.text.strip().replace("```json", "").replace("```", "").strip())
    except:
        pass

    clean_image = np.full_like(image, 255)
    for q in active_quadrants:
        if q == 1: clean_image[0:x_axis_y, y_axis_x:w_img] = image[0:x_axis_y, y_axis_x:w_img]
        if q == 2: clean_image[0:x_axis_y, 0:y_axis_x] = image[0:x_axis_y, 0:y_axis_x]
        if q == 3: clean_image[x_axis_y:h_img, 0:y_axis_x] = image[x_axis_y:h_img, 0:y_axis_x]
        if q == 4: clean_image[x_axis_y:h_img, y_axis_x:w_img] = image[x_axis_y:h_img, y_axis_x:w_img]
    cv2.line(clean_image, (0, x_axis_y), (w_img, x_axis_y), (255, 255, 255), 6)
    cv2.line(clean_image, (y_axis_x, 0), (y_axis_x, h_img), (255, 255, 255), 6)

    # 💡 [Step 3] 색상 기반 막대 추출 및 공간 필터링 + 몸통 컷오프 로직 추가
    print("-> 3. 색상 분석 및 몸통 컷오프 적용 중...")
    pixels = clean_image.reshape(-1, 3)
    unique_colors, counts = np.unique(pixels, axis=0, return_counts=True)
    sorted_indices = np.argsort(-counts)
    candidate_boxes = []
    for idx in sorted_indices:
        color = unique_colors[idx]
        if counts[idx] < 50 or np.all(color >= 240) or np.all(color <= 50): continue
        mask = cv2.inRange(clean_image, np.clip(color.astype(int) - tolerance, 0, 255).astype(np.uint8),
                           np.clip(color.astype(int) + tolerance, 0, 255).astype(np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if w > 5 and h > 10:
                cx, cy = x + w // 2, y + h // 2
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

                if is_valid_area:
                    # 💡 [핵심 복구] 행별 픽셀 밀도 스캔을 통한 몸통 분리 로직
                    mask_crop = mask[y:y + h, x:x + w]
                    row_counts = np.count_nonzero(mask_crop, axis=1)
                    threshold_w = max(1, w * 0.1)  # 너비의 15% 이상 채워져야 몸통으로 인정

                    # 아래(바닥)에서 위로 올라가며 몸통이 끝나는(에러 바/공백 시작) 지점 탐색
                    best_top, gap_count = h - 1, 0
                    for r in range(h - 1, -1, -1):
                        if row_counts[r] >= threshold_w:
                            best_top, gap_count = r, 0
                        else:
                            gap_count += 1
                            if gap_count >= 3: break  # 3픽셀 이상 끊기면 몸통 종료로 간주

                    new_y, new_h = y + best_top, h - best_top
                    if new_h > 5: candidate_boxes.append([x, new_y, w, new_h, color])

    merged_boxes = merge_overlapping_boxes(candidate_boxes, padding=con_tol)

    # [Step 4] Baseline 보정 및 눈금 검출
    y_coords = [b[1] for b in merged_boxes] + [b[1] + b[3] for b in merged_boxes]
    dynamic_zero_y = x_axis_y
    if y_coords:
        rounded_y = [int(round(yc / 2.0) * 2) for yc in y_coords]
        target_y = Counter(rounded_y).most_common(1)[0][0]
        dynamic_zero_y = int(np.mean([yc for yc in y_coords if abs(yc - target_y) <= 2]))

    refined_ticks_x = []
    tick_roi_x = binary_inv[x_axis_y + 1: x_axis_y + 10, :]
    col_counts_x = np.sum(tick_roi_x, axis=0)
    raw_ticks_x = [xi for xi, c in enumerate(col_counts_x) if
                   c > (tick_roi_x.shape[0] * 255 * 0.5) and (y_axis_x < xi < w_img)]
    if raw_ticks_x:
        temp_x = [raw_ticks_x[0]]
        for i in range(1, len(raw_ticks_x)):
            if raw_ticks_x[i] - raw_ticks_x[i - 1] < 5:
                temp_x.append(raw_ticks_x[i])
            else:
                refined_ticks_x.append(int(np.mean(temp_x)));
                temp_x = [raw_ticks_x[i]]
        refined_ticks_x.append(int(np.mean(temp_x)))

    tick_roi_y = binary_inv[:, max(0, y_axis_x - 10): y_axis_x]
    row_counts_y = np.sum(tick_roi_y, axis=1)
    raw_ticks_y = [yi for yi, count in enumerate(row_counts_y) if count > 2 * 255]
    if raw_ticks_y:
        ry, temp_y = [], [raw_ticks_y[0]]
        for i in range(1, len(raw_ticks_y)):
            if raw_ticks_y[i] - raw_ticks_y[i - 1] < 5:
                temp_y.append(raw_ticks_y[i])
            else:
                ry.append(int(np.mean(temp_y))); temp_y = [raw_ticks_y[i]]
        ry.append(int(np.mean(temp_y)))
        top_tick_y = min(ry)

    # [Step 5] 수위 경쟁(Water-Fill) 복구 엔진 (유지)
    print("-> 5. 수위 경쟁 스캔 중...")
    avg_w = int(np.mean([b[2] for b in merged_boxes])) if merged_boxes else 20
    recovered_boxes = []
    for tx in refined_ticks_x:
        if not any(bx - (avg_w // 2) <= tx <= bx + bw + (avg_w // 2) for (bx, by, bw, bh, bc) in merged_boxes):
            rx1, rx2 = max(0, tx - avg_w // 2), min(w_img, tx + avg_w // 2)
            roi_color = clean_image[0:h_img, rx1:rx2]
            valid_px = roi_color[np.logical_and(np.any(roi_color < 250, axis=2), np.any(roi_color > 50, axis=2))]
            if valid_px.size < 10:
                recovered_boxes.append(([rx1, dynamic_zero_y - 1, rx2 - rx1, 2], "0-Val"))
                continue
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
            _, labels, centers = cv2.kmeans(np.float32(valid_px), min(4, len(valid_px)), None, criteria, 10,
                                            cv2.KMEANS_RANDOM_CENTERS)
            best_h, best_y = 0, dynamic_zero_y
            for c_color in np.uint8(centers):
                if np.all(c_color >= 240) or np.all(c_color <= 50): continue
                col_fill = np.sum(
                    cv2.inRange(roi_color, np.clip(c_color.astype(int) - tolerance, 0, 255).astype(np.uint8),
                                np.clip(c_color.astype(int) + tolerance, 0, 255).astype(np.uint8)), axis=1)
                curr_h = 0
                for r in range(dynamic_zero_y - 1, 0, -1):
                    if col_fill[r] > (rx2 - rx1) * 0.1:
                        curr_h += 1
                    else:
                        break
                if curr_h > best_h: best_h, best_y = curr_h, dynamic_zero_y - curr_h
            recovered_boxes.append(([rx1, best_y, rx2 - rx1, max(2, best_h)], "MAX-Fill"))

    # [Step 6] 통합 시각화 (DEBUG)
    if DEBUG:
        cv2.line(debug_image, (0, x_axis_y), (w_img, x_axis_y), (0, 0, 255), 2)
        cv2.line(debug_image, (y_axis_x, 0), (y_axis_x, h_img), (0, 255, 255), 2)
        cv2.line(debug_image, (0, dynamic_zero_y), (w_img, dynamic_zero_y), (255, 0, 255), 2)
        for b in merged_boxes: cv2.rectangle(debug_image, (b[0], b[1]), (b[0] + b[2], b[1] + b[3]), (0, 255, 0), 2)
        for b, l in recovered_boxes:
            cv2.rectangle(debug_image, (b[0], b[1]), (b[0] + b[2], b[1] + b[3]), (0, 165, 255), 2)
            cv2.putText(debug_image, l, (b[0], b[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 165, 255), 1)
        for tx in refined_ticks_x: cv2.line(debug_image, (tx, x_axis_y), (tx, x_axis_y + 10), (255, 0, 0), 2)
        imwrite_korean(os.path.join(output_dir, f"debug_final_features_{base_name}"), debug_image)

    # [Step 7] Gemini Pro API 분석 및 최종 매핑
    print("-> 6. Gemini Pro API 분석 및 수치 맵핑 중...")
    y_max, y_min, gemini_x_labels = 0.0, 0.0, []
    try:
        img_pil = Image.open(image_path)
        prompt = """Analyze this bar chart. Return ONLY JSON: {"y_max": float, "y_min": float, "x_labels": ["label1", ...]}"""
        response = client.models.generate_content(model=MODEL_PRO, contents=[prompt, img_pil])
        data = json.loads(response.text.strip().replace("```json", "").replace("```", "").strip())
        y_max, y_min, gemini_x_labels = float(data.get("y_max", 0.0)), float(data.get("y_min", 0.0)), data.get(
            "x_labels", [])
    except Exception as e:
        print(f"   [API 오류]: {e}")

    scale_factor = (y_max / (dynamic_zero_y - top_tick_y)) if (
                top_tick_y is not None and dynamic_zero_y > top_tick_y) else 0
    refined_ticks_x.sort()
    x_labels_dict = {tx: (gemini_x_labels[i] if i < len(gemini_x_labels) else f"Tick_{i + 1}") for i, tx in
                     enumerate(refined_ticks_x)}

    final_data = []
    for (bx, by, bw, bh, bc) in merged_boxes:
        nearest_tx = min(refined_ticks_x, key=lambda tx: abs(tx - (bx + bw // 2))) if refined_ticks_x else (
                    bx + bw // 2)
        dist_top, dist_bottom = abs(by - dynamic_zero_y), abs((by + bh) - dynamic_zero_y)
        p_height = (dynamic_zero_y - by) if dist_bottom <= dist_top + 3 else (dynamic_zero_y - (by + bh))
        final_data.append({"X_Label": x_labels_dict.get(nearest_tx, "Unknown"), "Pixel_Height": p_height,
                           "Actual_Value": round(p_height * scale_factor, 2), "Type": "Normal"})

    for (rx, ry, rw, rh), t_label in recovered_boxes:
        nearest_tx = min(refined_ticks_x, key=lambda tx: abs(tx - (rx + rw // 2))) if refined_ticks_x else (
                    rx + rw // 2)
        p_h = 0 if t_label == "0-Val" else (
            dynamic_zero_y - ry if abs(ry - dynamic_zero_y) > abs(ry + rh - dynamic_zero_y) else dynamic_zero_y - (
                        ry + rh))
        final_data.append({"X_Label": x_labels_dict.get(nearest_tx, "Unknown"), "Pixel_Height": p_h,
                           "Actual_Value": round(p_h * scale_factor, 2), "Type": "Recovered_" + t_label})

    df = pd.DataFrame(final_data)
    if not df.empty:
        csv_path = os.path.join(output_dir, f"extracted_data_{base_name}.csv")
        df.to_csv(csv_path, index=False)
        print(f"-> [추출 완료] CSV 저장됨: {csv_path}")


if __name__ == "__main__":
    extract_bars_with_ocr_and_merge(image_path='./Example_Figs/fig2g.png', tolerance=5, DEBUG=True)