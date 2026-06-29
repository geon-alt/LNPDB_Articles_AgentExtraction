import os
import sys
import json
import pandas as pd
from pathlib import Path
from PIL import Image

# --- [경로 설정] ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Bar_Plot import extract_bars_with_ocr_and_merge
from Point_Plot import extract_point_plot_data
from find_api import find_api_key_file, get_vertexai_client
from google.genai import types

MODEL_FLASH = "gemini-2.5-flash"
API_JSON_NAME = "vertex-490605-8d0be916872a.json"


def classify_plot_type(client, image_path: str):
    try:
        img_pil = Image.open(image_path)
        prompt = """
        Analyze this scientific chart image.
        Classify it into one of the following exact strings based on its visual representation:
        - "bar_plot"
        - "point_plot" 
        - "box_plot" 
        - "heatmap" 
        - "other" 

        Return ONLY a JSON object exactly like this: {"plot_type": "bar_plot"}
        """
        response = client.models.generate_content(
            model=MODEL_FLASH,
            contents=[prompt, img_pil],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        data = json.loads(response.text.strip().replace("```json", "").replace("```", "").strip())
        return data.get("plot_type", "other")
    except Exception as e:
        print(f"      ! 분류 API 에러: {e}")
        return "other"


def process_extraction_from_root(root_path: Path, client):
    classified_csv = root_path / "fig_table_lnpdb_classified.csv"
    mapping_json = root_path / "total_figure_mapping.json"

    if not classified_csv.exists():
        print(f"❌ 에러: '{classified_csv.name}' 파일이 없습니다.")
        return
    if not mapping_json.exists():
        print(f"❌ 에러: '{mapping_json.name}' 파일이 없습니다.")
        return

    print(f"\n📂 최상위 폴더 데이터 로드 완료: {root_path.name}")

    df_cls = pd.read_csv(classified_csv)
    if 'matched_excel_sheet' not in df_cls.columns:
        df_cls['matched_excel_sheet'] = ''

    target_df = df_cls[
        (df_cls['need_for_lnpdb'].isin(['yes', 'maybe'])) &
        (df_cls['matched_excel_sheet'].isna() | (df_cls['matched_excel_sheet'] == ''))
        ]
    target_items = target_df['item_id'].tolist()

    if not target_items:
        print("  -> 이미지 기반 추출 대상이 없습니다.")
        return

    with open(mapping_json, 'r', encoding='utf-8') as f:
        total_mapping = json.load(f)

    for folder_name, folder_data in total_mapping.items():
        folder_path = root_path / folder_name
        if not folder_path.exists():
            continue

        print(f"\n  🔍 하위 폴더 분석 시작: {folder_name}")
        output_dir = folder_path / "extracted_plot_values"
        os.makedirs(output_dir, exist_ok=True)
        all_extracted_data = []

        for item_id, item_info in folder_data.items():
            # 💡 [핵심 해결] item_info가 None(null)이거나 딕셔너리가 아닌 경우 스킵하도록 안전장치 추가
            if item_id not in target_items or not isinstance(item_info, dict) or "panels" not in item_info:
                continue

            panels = item_info["panels"]
            for p_id, img_path_str in panels.items():
                img_path = Path(img_path_str)
                local_img_path = folder_path / "separated_panels_gemini" / img_path.name

                if not local_img_path.exists():
                    print(f"      ! 이미지를 찾을 수 없습니다: {local_img_path.name}")
                    continue

                base_img_name = local_img_path.name
                print(f"    -> 패널 분석 중: {item_id} (Panel {p_id})")

                plot_type = classify_plot_type(client, str(local_img_path))
                print(f"        - 분류 결과: {plot_type}")
                csv_to_read = None

                if plot_type == "bar_plot":
                    extract_bars_with_ocr_and_merge(str(local_img_path), output_dir=str(output_dir), DEBUG=True)
                    csv_to_read = output_dir / f"extracted_data_{base_img_name}.csv"

                elif plot_type == "point_plot":
                    extract_point_plot_data(str(local_img_path), output_dir=str(output_dir), DEBUG=True)
                    csv_to_read = output_dir / f"extracted_points_{base_img_name}.csv"

                elif plot_type in ["box_plot", "heatmap", "other"]:
                    print(f"        - ⚠️ 추출 제외 대상이거나 미구현된 그래프입니다 ({plot_type}).")
                    continue

                if csv_to_read and csv_to_read.exists():
                    try:
                        df_temp = pd.read_csv(csv_to_read)
                        df_temp.insert(0, 'Item_ID', item_id)
                        df_temp.insert(1, 'Panel_ID', p_id)
                        df_temp.insert(2, 'Plot_Type', plot_type)
                        df_temp.insert(3, 'Source_Image', base_img_name)
                        all_extracted_data.append(df_temp)
                    except Exception as e:
                        print(f"        ! CSV 읽기 실패: {e}")

        if all_extracted_data:
            final_df = pd.concat(all_extracted_data, ignore_index=True)
            final_csv_path = folder_path / "final_merged_plot_data.csv"
            final_df.to_csv(final_csv_path, index=False, encoding='utf-8-sig')
            print(f"    ✨ [{folder_name}] 통합 파일 저장 완료: {final_csv_path.name}")
        else:
            print(f"    ⚠️ [{folder_name}] 추출된 데이터가 없습니다.")


if __name__ == "__main__":
    TARGET_ROOT_FOLDER = Path(r"G:\내 드라이브\EXTRACT-TEST\BEND-test")

    try:
        api_key = find_api_key_file(API_JSON_NAME)
        vertex_client = get_vertexai_client(api_key)
        print("✅ Vertex AI 클라이언트 초기화 완료")

        if TARGET_ROOT_FOLDER.exists() and TARGET_ROOT_FOLDER.is_dir():
            print(f"\n▶️ [{TARGET_ROOT_FOLDER.name}] 최상위 매핑 데이터 기반 추출 시작\n" + "=" * 50)
            process_extraction_from_root(TARGET_ROOT_FOLDER, vertex_client)
            print("\n" + "=" * 50 + "\n✅ 모든 폴더 처리 완료!")
        else:
            print(f"❌ 폴더를 찾을 수 없습니다. 경로를 확인해주세요: {TARGET_ROOT_FOLDER}")

    except Exception as e:
        print(f"❌ 실행 실패: {e}")