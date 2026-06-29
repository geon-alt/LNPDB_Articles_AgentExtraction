import os
import time
import pandas as pd
from google import genai
from google.genai import types
import json

# 상위 폴더의 find_api 모듈 불러오기
import sys
from pathlib import Path
current_dir = Path(__file__).resolve().parent
sys.path.append(str(current_dir.parent))
from find_api import find_api_key_file, get_vertexai_client

# 1. API 및 모델 설정
key_path = find_api_key_file("vertex-490605-8d0be916872a.json")
client = get_vertexai_client(key_path)

MODEL_ID = 'gemini-3.1-pro-preview'
FALLBACK_MODEL_ID = 'gemini-3.1-pro-preview'

# 💡 바이트 변환 함수
def get_document_part(file_path_str):
    print(f"  - 파일 바이트화 중: {os.path.basename(file_path_str)}")
    with open(file_path_str, "rb") as f:
        file_bytes = f.read()
    return types.Part.from_bytes(data=file_bytes, mime_type="text/plain")

def extract_python_code(text):
    if "```python" in text:
        return text.split("```python")[1].split("```")[0].strip()
    elif "```" in text:
        return text.replace("```", "").strip()
    return text.strip()

def generate_and_execute_code(doc_part, csv_path, csv_filename, item_ids_str, is_retry=False, error_msg=None):
    current_model = FALLBACK_MODEL_ID if is_retry else MODEL_ID

    base_prompt = f"""
    당신은 Python 및 Pandas 데이터 전처리 전문가입니다.
    첨부된 CSV 파일의 구조를 분석하여, 이 데이터를 정해진 규칙에 맞게 변환하는 파이썬 코드를 작성하세요.

    [입력/출력 변수 환경 (매우 중요)]
    - 환경에는 `csv_file_path` 라는 변수에 이 CSV 파일의 경로가 문자열로 담겨있습니다.
    - 코드는 `csv_file_path`를 `pd.read_csv()`로 읽어서 처리해야 합니다.
    - 최종 처리된 DataFrame은 반드시 `result_df` 라는 변수명에 할당하세요.

    [대상 정보]
    - 이 데이터의 원본 파일명은 '{csv_filename}' 입니다.
    - 이 데이터와 연관된 Item_ID들은 다음과 같습니다: {item_ids_str}

    [데이터 변환 규칙]
    1. 데이터를 분석하여 'formulation_id'(예: C8-200 등)가 어디 있는지 찾으세요.
    2. 최종 `result_df`는 정확히 다음 6개의 컬럼만 가져야 합니다:
       `['Matched_Sheet_File', 'Item_ID', 'formulation_id', '구분컬럼', '실험수치들', '실험수치1']`
    3. 모든 행의 'Matched_Sheet_File' 컬럼에는 '{csv_filename}' 를 넣고, 'Item_ID' 컬럼에는 '{item_ids_str}' 를 넣으세요.
    4. [경우 A] 단일 테이블에 여러 실험 수치가 있는 경우:
       - `구분컬럼`: 원래 컬럼명(예: Size, PDI)
       - `실험수치1`: 해당 실험값
       - `실험수치들`: "" (빈 문자열)
    5. [경우 B] 제형별로 측정값(숫자)만 여러 개 나열된 경우:
       - `구분컬럼`: ""
       - `실험수치들`: 반복된 측정값들을 문자열 형태의 세미콜론(;)으로 연결 (예: "72;70;68")
       - `실험수치1`: 해당 수치들의 산술 평균값

    오직 실행 가능한 순수 파이썬 코드만 ```python ``` 블록에 담아 반환하세요. 설명은 필요 없습니다. `import pandas as pd`를 포함하세요.
    """

    if is_retry:
        base_prompt = f"[긴급: 이전 코드 실행 실패] 에러: {error_msg}\n" + base_prompt

    try:
        response = client.models.generate_content(
            model=current_model,
            contents=[doc_part, base_prompt]
        )
        ai_code = extract_python_code(response.text)

        local_vars = {'csv_file_path': csv_path}
        exec(ai_code, globals(), local_vars)
        result_df = local_vars.get('result_df')

        if result_df is not None and not result_df.empty:
            return True, result_df, None
        return False, None, "결과 DataFrame이 비어있습니다."
    except Exception as e:
        return False, None, str(e)

def standardize_via_code_generation(mapping_excel_path, sheets_folder_path):
    print(f"\n{'=' * 60}\n[작업 시작] 파이썬 코드 자동 생성 모드\n{'=' * 60}")

    df_map = pd.read_excel(mapping_excel_path)
    valid_matches = df_map[(df_map['Matched_Sheet_File'].notna()) & 
                           (df_map['Matched_Sheet_File'].astype(str).str.lower() != 'not matched')]

    csv_to_items = {}
    for _, row in valid_matches.iterrows():
        item_id = str(row['Item_ID']).strip()
        for fname in str(row['Matched_Sheet_File']).split(','):
            fname = fname.strip()
            if not fname: continue
            if fname not in csv_to_items: csv_to_items[fname] = []
            csv_to_items[fname].append(item_id)

    final_dfs = []
    for idx, (csv_filename, item_ids) in enumerate(csv_to_items.items(), 1):
        item_ids_str = ", ".join(set(item_ids))
        csv_path = os.path.join(sheets_folder_path, csv_filename)
        print(f"  [{idx}/{len(csv_to_items)}] 분석: {csv_filename}")

        if not os.path.exists(csv_path): continue

        try:
            doc_part = get_document_part(csv_path)
            success, result_df, err = generate_and_execute_code(doc_part, csv_path, csv_filename, item_ids_str)
            
            if not success:
                print(f"    -> [재시도] {FALLBACK_MODEL_ID} 사용 중...")
                success, result_df, err = generate_and_execute_code(doc_part, csv_path, csv_filename, item_ids_str, is_retry=True, error_msg=err)

            if success:
                final_dfs.append(result_df)
                print(f"    -> [성공] {len(result_df)}행 추출")
        except Exception as e:
            print(f"    -> [에러] {e}")
        time.sleep(2)

    if final_dfs:
        master_df = pd.concat(final_dfs, ignore_index=True)
        out_path = os.path.join(os.path.dirname(mapping_excel_path), "standardized_experimental_data.xlsx")
        master_df.to_excel(out_path, index=False)
        print(f"\n✨ 저장 완료: {out_path}")

def main():
    # 경로를 본인 환경에 맞게 수정하세요
    MAPPING_EXCEL_PATH = r"/Users/kogeon/Library/CloudStorage/GoogleDrive-geon@molcube.com/내 드라이브/BEND_meta/BEND/sheet_mapping_result.xlsx"
    SHEETS_FOLDER_PATH = r"/Users/kogeon/Library/CloudStorage/GoogleDrive-geon@molcube.com/내 드라이브/BEND_meta/sheets_folder"
    standardize_via_code_generation(MAPPING_EXCEL_PATH, SHEETS_FOLDER_PATH)

if __name__ == "__main__":
    main()