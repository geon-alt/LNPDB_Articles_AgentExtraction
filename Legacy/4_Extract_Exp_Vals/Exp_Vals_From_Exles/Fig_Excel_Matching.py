import os
import json
import time
import re
import pandas as pd
from google import genai
from google.genai import types

import sys
from pathlib import Path
current_dir = Path(__file__).resolve().parent
sys.path.append(str(current_dir.parent))
from find_api import find_api_key_file, get_vertexai_client

# 1. API 키 설정 및 초기화
key_path = find_api_key_file("vertex-490605-8d0be916872a.json")
client = get_vertexai_client(key_path)

MODEL_ID = 'gemini-3.1-pro-preview'

def split_excel_and_get_csvs(excel_path):
    print(f"  [전처리] '{os.path.basename(excel_path)}' 분리 중...")
    base_dir = os.path.dirname(excel_path)
    base_filename = os.path.splitext(os.path.basename(excel_path))[0]
    new_folder_path = os.path.join(base_dir, f"{base_filename}_sheets")
    os.makedirs(new_folder_path, exist_ok=True)

    xls = pd.ExcelFile(excel_path)
    saved_files = []
    for sheet_name in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet_name)
        safe_name = re.sub(r'[\\/*?:"<>|]', "_", sheet_name)
        output_path = os.path.join(new_folder_path, f"{base_filename}_{safe_name}.csv")
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        saved_files.append(output_path)
    return saved_files

# 💡 바이트 변환 함수
def get_document_part(file_path_str):
    with open(file_path_str, "rb") as f:
        file_bytes = f.read()
    return types.Part.from_bytes(data=file_bytes, mime_type="text/plain")

def process_exact_mapping(meta_excel_path, target_data_excel_path):
    print(f"\n{'=' * 60}\n[매칭 작업] 시작\n{'=' * 60}")

    df_meta = pd.read_excel(meta_excel_path)
    target_items = df_meta[df_meta['Extractable'] == 'O']['Item_ID'].dropna().astype(str).tolist()
    
    target_csv_paths = split_excel_and_get_csvs(target_data_excel_path)
    final_mapping_result = {item: "Not Matched" for item in target_items}

    for idx, csv_path in enumerate(target_csv_paths, 1):
        csv_filename = os.path.basename(csv_path)
        print(f"  [{idx}/{len(target_csv_paths)}] 분석 중: {csv_filename}", end=" ")

        try:
            doc_part = get_document_part(csv_path)
            prompt = f"""
            분석 대상 CSV 파일명: {csv_filename}
            [전체 분석 대상 Item ID 목록]: {target_items}
            이 CSV 파일과 매칭되는 Item ID를 목록(JSON 배열)으로 반환하세요. 없으면 []를 반환하세요.
            """

            res = client.models.generate_content(
                model=MODEL_ID, 
                contents=[doc_part, prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            matched_items_list = json.loads(res.text)

            if isinstance(matched_items_list, list) and matched_items_list:
                print(f"-> 매칭: {matched_items_list}")
                for item in matched_items_list:
                    if item in final_mapping_result:
                        if final_mapping_result[item] == "Not Matched":
                            final_mapping_result[item] = csv_filename
                        else:
                            final_mapping_result[item] += f", {csv_filename}"
            else:
                print("-> 매칭 없음")
        except Exception as e:
            print(f"-> 오류: {e}")
        time.sleep(2)

    result_rows = [{"Item_ID": k, "Matched_Sheet_File": v} for k, v in final_mapping_result.items()]
    out_path = os.path.join(os.path.dirname(meta_excel_path), f"sheet_mapping_{os.path.basename(target_data_excel_path)}")
    pd.DataFrame(result_rows).to_excel(out_path, index=False)
    print(f"\n✨ 저장 완료: {out_path}")

def main():
    META_PATH = r"/Users/kogeon/Library/CloudStorage/GoogleDrive-geon@molcube.com/내 드라이브/BEND_meta/BEND/BEND_metadata.xlsx"
    DATA_PATH = r"/Users/kogeon/Library/CloudStorage/GoogleDrive-geon@molcube.com/내 드라이브/BEND_meta/target_data.xlsx"
    process_exact_mapping(META_PATH, DATA_PATH)

if __name__ == "__main__":
    main()