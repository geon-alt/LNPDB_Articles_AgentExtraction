import os
import sys
import json
import argparse
import pandas as pd
from pathlib import Path
from google.genai import types
import re
# --- [경로 설정] 프로젝트 최상위 경로를 sys.path에 추가 ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from find_api import get_genai_client, find_api_key_file
from LLM_API import generate_content_with_guard

# 설정
MODEL_NAME = "gemini-3-flash-preview"
API_MODE = "vertex"  # "vertex" 또는 "aistudio"
API_JSON_NAME = "vertex-490605-8d0be916872a.json"
API_TXT_NAME = "gemini_api.txt"
PROJECT_ID = "vertex-490605"
LOCATION = "global"
MAX_INPUT_TOKENS = 160000
TOKEN_COUNT_ONLY = False

EXCEL_MATCH_COLUMNS = [
    "excel_item_id",
    "matched_blocks",
    "matched_block_ids",
    "matched_block_files",
    "excel_block_id",
    "excel_block_file",
    "excel_sheet",
    "matched_sheet",
    "matched_sheet_file",
]

EMPTY_EXCEL_VALUES = {"", "nan", "none", "null", "[]", "{}"}
EMPTY_MANUAL_VALUES = {"", "nan", "none", "null", "[]", "{}"}

def normalize_ft_item_id(value):
    s = str(value or "").strip().lower()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\bextended\s+data\s+fig\.", "extended data figure", s)
    s = re.sub(r"\bextended\s+data\s+fig\b", "extended data figure", s)
    s = re.sub(r"\bextended\s+data\s+figure\b", "extended data figure", s)
    s = re.sub(r"\bextended\s+data\s+table\b", "extended data table", s)
    s = re.sub(r"\bsupplementary\s+fig\.", "supplementary figure", s)
    s = re.sub(r"\bsupplementary\s+fig\b", "supplementary figure", s)
    s = re.sub(r"\bsupp\.?\s+fig\.", "supplementary figure", s)
    s = re.sub(r"\bsupp\.?\s+fig\b", "supplementary figure", s)
    s = re.sub(r"\bsupp\.?\s+table\.", "supplementary table", s)
    s = re.sub(r"\bsupp\.?\s+table\b", "supplementary table", s)
    s = re.sub(r"\bfig\.", "figure", s)
    s = re.sub(r"\bfig\b", "figure", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def get_document_part(file_path: Path):
    mime_type = "text/plain" if file_path.suffix.lower() == ".md" else "application/pdf"
    with open(file_path, "rb") as f:
        return types.Part.from_bytes(data=f.read(), mime_type=mime_type)

# --- helper function: count_tokens_with_retry ---
def count_tokens_with_retry(client, model_name, contents, prompt_text, max_retries=5, base_wait=15):
    """document parts + prompt_text 조합에 대해 count_tokens를 재시도하며 계산합니다."""
    full_contents = list(contents) + [prompt_text]

    for attempt in range(max_retries):
        try:
            result = client.models.count_tokens(
                model=model_name,
                contents=full_contents,
            )
            total_tokens = getattr(result, "total_tokens", None)
            if total_tokens is None:
                raise ValueError("count_tokens 결과에 total_tokens가 없습니다.")
            return int(total_tokens)

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                wait_time = base_wait * (2 ** attempt)
                print(f"    ! [429 count_tokens 쿼터 초과] {wait_time}초 대기 후 재시도 중... ({attempt + 1}/{max_retries})")
                import time
                time.sleep(wait_time)
            else:
                raise

    raise RuntimeError("count_tokens 최대 재시도 횟수 초과")

def is_meaningful_manual_value(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    text = str(value).strip().lower()
    return text not in EMPTY_MANUAL_VALUES

def normalize_manual_select(value) -> str:
    text = str(value).strip().lower()
    if text in EMPTY_MANUAL_VALUES:
        return ""
    if text in {"yes", "y", "1", "true"}:
        return "yes"
    if text == "maybe":
        return "maybe"
    if text in {"no", "n", "0", "false"}:
        return "no"
    return "no"

def get_fig_selection_value(row):
    manual = row.get("manual_select", "")
    if is_meaningful_manual_value(manual):
        return normalize_manual_select(manual)

    return str(row.get("need_for_lnpdb", "")).strip().lower()

def is_meaningful_excel_value(value) -> bool:
    if value is None:
        return False

    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass

    if isinstance(value, str):
        return value.strip().lower() not in EMPTY_EXCEL_VALUES

    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0

    return True

def row_has_excel_match(row: pd.Series, excel_cols: list[str]) -> bool:
    return any(is_meaningful_excel_value(row.get(col)) for col in excel_cols)

def filter_excel_covered_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    excel_cols = [col for col in EXCEL_MATCH_COLUMNS if col in df.columns]
    if not excel_cols:
        return df.copy(), df.iloc[0:0].copy()

    excel_match_mask = df.apply(row_has_excel_match, axis=1, excel_cols=excel_cols)
    remaining_df = df[~excel_match_mask].copy()
    excluded_df = df[excel_match_mask].copy()
    return remaining_df, excluded_df

def match_items_to_images(client, doc_parts, item_ids, image_list, token_count_only=False, max_input_tokens=160000):
    """
    01_Marker에서 생성된 실제 이미지 파일 목록과,
    01/02 단계에서 추출된 figure/table ID 목록을
    Markdown 및 PDF 문맥을 바탕으로 LLM을 이용해 매칭한다.

    Args:
        client:
            Gemini API 호출에 사용하는 클라이언트 객체.
            토큰 수 계산(count) 및 실제 매칭 요청(generate)에 사용된다.
    
        doc_parts:
            Markdown, PDF 등 문서 본문/캡션/페이지 문맥이 포함된 입력 파트 리스트.
            각 figure/table ID가 어떤 실제 이미지 파일에 해당하는지
            문서 전체 문맥을 참고하여 판단하기 위해 사용된다.
    
        item_ids:
            매칭 대상이 되는 figure/table ID 목록.
            예: ["figure 1", "figure 2a", "table 1"]
    
        image_list:
            폴더 내 실제 이미지 파일 정보 목록.
            일반적으로 각 원소는 path 등을 포함한 dict이며,
            LLM은 이 목록 중 어떤 파일이 각 item_id와 대응되는지 선택한다.
    
        token_count_only:
            True이면 실제 매칭 API 호출은 하지 않고,
            현재 입력(doc_parts + prompt)이 몇 토큰인지 계산만 수행한다.
            False이면 실제 매칭을 수행한다.
    
        max_input_tokens:
            허용할 최대 입력 토큰 수.
            token_count_only=True일 때 초과 여부 판단 기준으로 사용된다.
    
    Returns:
        dict:
            기본적으로 각 item_id를 key로, 매칭된 이미지 파일의 path를 value로 하는 dict를 반환한다.
            확실한 매칭이 없으면 해당 값은 null(None)이어야 한다.
    
            예:
            {
                "figure 1": "/path/to/_page_3_Picture_1.jpeg",
                "table 2": None
            }
    
            단, token_count_only=True인 경우에는 실제 매칭 결과 대신
            아래와 같은 토큰 계산 정보 dict를 반환한다:
            {
                "_token_count_only": True,
                "counted_input_tokens": int,
                "max_input_tokens": int,
                "is_over_limit": bool
            }
    
            오류 발생 시 또는 매칭 실패 시에는 빈 dict({})를 반환할 수 있다.    
    """
    if not image_list: return {}
    
    prompt = f"""
    당신은 논문 분석 전문가입니다.
    대상 Figure/Table ID 목록: {item_ids}
    폴더 내 실제 이미지 파일 목록: {json.dumps(image_list, ensure_ascii=False, indent=2)}
    
    [지시]
    1. 제공된 Markdown/PDF 내용을 참고하여 각 ID(예: figure 1)가 어떤 이미지 파일(예: _page_0_Picture_1.jpeg)과 일치하는지 분석하세요.
    2. 결과는 각 Item ID를 키로, 매칭된 이미지의 'path'를 값으로 하는 JSON 객체로만 반환하세요.
    3. 확실한 매칭이 없으면 null로 표시하세요.
    4. Extended Data figures are valid figure identifiers. Match 'extended data figure 1' to image labels such as 'Extended Data Fig. 1' or 'Extended Data Figure 1'. Keep them distinct from main Fig. 1 and Supplementary Fig. 1.
    """

    if token_count_only:
        counted_input_tokens = count_tokens_with_retry(
            client=client,
            model_name=MODEL_NAME,
            contents=doc_parts,
            prompt_text=prompt,
        )
        print(f"    🔢 토큰 계산 전용 모드")
        print(f"    - counted_input_tokens: {counted_input_tokens:,}")
        print(f"    - max_input_tokens: {max_input_tokens:,}")
        print(f"    - 초과 여부: {counted_input_tokens > max_input_tokens}")
        return {
            "_token_count_only": True,
            "counted_input_tokens": counted_input_tokens,
            "max_input_tokens": max_input_tokens,
            "is_over_limit": counted_input_tokens > max_input_tokens,
        }
    
    max_retries = 5
    base_wait = 15

    for attempt in range(max_retries):
        try:
            response = generate_content_with_guard(
                client=client,
                model_name=MODEL_NAME,
                contents=doc_parts,
                prompt_text=prompt,
                response_mime_type="application/json",
            )

            if hasattr(response, "response_text") and response.response_text is not None:
                raw_text = response.response_text
            elif hasattr(response, "text") and response.text is not None:
                raw_text = response.text
            elif hasattr(response, "response") and hasattr(response.response, "text") and response.response.text is not None:
                raw_text = response.response.text
            else:
                raise AttributeError(
                    f"응답 객체에서 텍스트를 찾을 수 없습니다. type={type(response).__name__}"
                )

            text = raw_text.replace("```json", "").replace("```", "").strip()
            return json.loads(text)
            
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                wait_time = base_wait * (2 ** attempt)
                print(f"    ! [429 쿼터 초과] {wait_time}초 대기 후 재시도 중... ({attempt + 1}/{max_retries})")
                import time
                time.sleep(wait_time)
            elif "400" in error_msg or "INVALID_ARGUMENT" in error_msg:
                print(f"    ! [400 토큰 초과] 문서/이미지 데이터가 한도를 초과했습니다. 매핑을 건너뜁니다.")
                return {}
            else:
                print(f"    ! 알 수 없는 API 에러 발생: {type(e).__name__}: {e}")
                return {}

    print("    ! 최대 재시도 횟수 초과로 매핑 실패")
    return {}

def process_folder_mapping(
    folder_path: Path,
    client,
    token_count_only=False,
    max_input_tokens=160000,
    classified_csv_path=None,
    exclude_excel_covered=False,
    mapping_output_path=None,
    debug_classified_output_path=None,
):
    """
    개별 폴더를 스캔하여 매핑 딕셔너리를 반환합니다.
    """
    folder_path = Path(folder_path)
    if classified_csv_path is None:
        classified_csv = folder_path / "fig_table_lnpdb_classified.csv" # 02 에서 만든 필요한 fig CSV 경로
        if not classified_csv.exists():
            classified_csv = folder_path.parent / "fig_table_lnpdb_classified.csv"
            if not classified_csv.exists():
                return None
    else:
        classified_csv = Path(classified_csv_path)
        if not classified_csv.exists():
            print(f"  ! classified CSV를 찾을 수 없습니다: {classified_csv}")
            return None

    try: 
        df = pd.read_csv(classified_csv)
        total_classified_rows = len(df)
        detected_excel_cols = [col for col in EXCEL_MATCH_COLUMNS if col in df.columns]

        print(f"  📄 classified CSV path: {classified_csv}")
        print(f"  - total classified rows: {total_classified_rows}")
        print(f"  - detected Excel-related columns: {detected_excel_cols if detected_excel_cols else 'none'}")

        if exclude_excel_covered and detected_excel_cols:
            df_for_mapping, excel_excluded_df = filter_excel_covered_rows(df)
        else:
            df_for_mapping = df.copy()
            excel_excluded_df = df.iloc[0:0].copy()
        if "item_id" in df_for_mapping.columns:
            df_for_mapping["item_id"] = df_for_mapping["item_id"].apply(normalize_ft_item_id)
        if "base_id" in df_for_mapping.columns:
            df_for_mapping["base_id"] = df_for_mapping["base_id"].apply(normalize_ft_item_id)

        excluded_count = len(excel_excluded_df)
        remaining_count = len(df_for_mapping)
        print(f"  - rows excluded because Excel coverage exists: {excluded_count}")
        print(f"  - rows remaining after Excel exclusion: {remaining_count}")

        if excluded_count > 0:
            excel_excluded_path = folder_path / "figure_mapping_excel_covered_excluded.csv"
            excel_excluded_df.to_csv(excel_excluded_path, index=False, encoding="utf-8-sig")
            print(f"  - Excel-covered excluded rows saved: {excel_excluded_path}")

        figure_mapping_input_path = (
            Path(debug_classified_output_path)
            if debug_classified_output_path is not None
            else folder_path / "fig_table_lnpdb_classified_for_figure_mapping.csv"
        )
        df_for_mapping.to_csv(figure_mapping_input_path, index=False, encoding="utf-8-sig")
        print(f"  - figure mapping classified rows saved: {figure_mapping_input_path}")

        # get_fig_selection_value 함수를 적용하여 _fig_select 컬럼 생성 : "manual_select"이 "yes"로 명확히 선택된 경우 "yes", "no"로 명확히 제외된 경우 "no", 그렇지 않은 경우 "need_for_lnpdb" 값을 따르도록 함
        df_for_mapping["_fig_select"] = df_for_mapping.apply(get_fig_selection_value, axis=1)
        if "manual_select" in df_for_mapping.columns:
            manual_has_value = df_for_mapping["manual_select"].apply(is_meaningful_manual_value)
            manual_norm = df_for_mapping["manual_select"].apply(normalize_manual_select)
            print(f"  - manual_select override rows: {int(manual_has_value.sum())}")
            print(f"  - manual_select include rows yes/maybe: {int((manual_has_value & manual_norm.isin(['yes', 'maybe'])).sum())}")
            print(f"  - manual_select exclude rows no/invalid: {int((manual_has_value & ~manual_norm.isin(['yes', 'maybe'])).sum())}")

        # 이전 필요하다고 판단된 fig 만을 선택
        target_items = (
            df_for_mapping[df_for_mapping["_fig_select"].isin(["yes", "maybe"])]["item_id"]
            .astype(str)
            .map(normalize_ft_item_id)
            .unique()
            .tolist()
        ) 
        print(f"  - final target_items selected by manual_select / need_for_lnpdb: {len(target_items)}")


        # marker 가 pdf 에서 잘라낸 이미지 파일 탐색
        image_exts = {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}
        image_list = []
        doc_files = []

        for f in folder_path.rglob('*'):  # 하위 폴더(Marker가 만든 폴더)까지 모두 탐색
            if f.is_file():
                if f.suffix.lower() in image_exts:
                    image_list.append({"filename": f.name, "path": str(f)})
                elif f.suffix.lower() in {'.md', '.pdf'}:
                    doc_files.append(f)

        if not target_items or not image_list or not doc_files:
            return None # 필요한 데이터가 없는 경우 None 반환

        # 매핑 분석 시작
        print(f"  🔍 {folder_path.name} 매핑 분석 중...")
        doc_parts = [get_document_part(f) for f in doc_files]
        mapping_result = match_items_to_images(
            client,
            doc_parts,
            target_items,
            image_list,
            token_count_only=token_count_only,
            max_input_tokens=max_input_tokens,
        )

        if mapping_output_path is not None and mapping_result:
            mapping_output_path = Path(mapping_output_path)
            with open(mapping_output_path, "w", encoding="utf-8") as f:
                json.dump({folder_path.name: mapping_result}, f, indent=4, ensure_ascii=False)
            print(f"  ✅ mapping output saved: {mapping_output_path}")

        return mapping_result  # 결과를 저장하지 않고 반환만 함

    except Exception as e:
        print(f"  ! {folder_path.name} 에러: {e}")
        return None

# Main 실행 로직 분리
def run_mapping_main(
    root_dir,
    model_name="gemini-3-flash-preview",
    api_mode="vertex",
    api_json_name="vertex-490605-8d0be916872a.json",
    api_txt_name="gemini_api.txt",
    project_id="vertex-490605",
    location="global",
    token_count_only=False,
    max_input_tokens=160000,
    classified_csv_path=None,
    exclude_excel_covered=False,
):
    root_dir = Path(root_dir)

    global MODEL_NAME, API_MODE, API_JSON_NAME, API_TXT_NAME, PROJECT_ID, LOCATION, TOKEN_COUNT_ONLY, MAX_INPUT_TOKENS
    MODEL_NAME = model_name
    API_MODE = api_mode
    API_JSON_NAME = api_json_name
    API_TXT_NAME = api_txt_name
    PROJECT_ID = project_id
    LOCATION = location
    TOKEN_COUNT_ONLY = token_count_only
    MAX_INPUT_TOKENS = max_input_tokens

    if API_MODE == "vertex":
        client = get_genai_client(
            mode="vertex",
            key_path=API_JSON_NAME if API_JSON_NAME else None,
            project=PROJECT_ID,
            location=LOCATION,
        )
        print("✅ Vertex AI 클라이언트 초기화 완료")
    elif API_MODE == "aistudio":
        client = get_genai_client(
            mode="aistudio",
            filename=API_TXT_NAME,
        )
        print("✅ AI Studio 클라이언트 초기화 완료")
    else:
        raise ValueError("API_MODE는 'vertex' 또는 'aistudio' 여야 합니다.")

    subfolders = sorted([p for p in root_dir.iterdir() if p.is_dir() and not p.name.startswith('.')])
    print(f"📂 총 {len(subfolders)}개 폴더 탐색 및 통합 매핑 시작\n" + "="*50)

    total_mapping = {}

    for folder in subfolders:
        res = process_folder_mapping(
            folder,
            client,
            token_count_only=TOKEN_COUNT_ONLY,
            max_input_tokens=MAX_INPUT_TOKENS,
            classified_csv_path=classified_csv_path,
            exclude_excel_covered=exclude_excel_covered,
        )
        if res:
            total_mapping[folder.name] = res
            print(f"  ✅ {folder.name}: 매핑 수집 완료")

    if total_mapping:
        save_name = "total_figure_mapping_token_count.json" if TOKEN_COUNT_ONLY else "total_figure_mapping.json"
        save_path = root_dir / save_name
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(total_mapping, f, indent=4, ensure_ascii=False)
        print("\n" + "=" * 50)
        print(f"✨ 통합 매핑 파일 저장 성공: {save_path}")

    return total_mapping

if __name__ == "__main__":
    ROOT_DIR = r"/Users/kogeon/Google Drive/내 드라이브/LNPDB_new/ZT_2026"

    MAIN_MODEL_NAME = "gemini-3.1-pro-preview"
    MAIN_API_MODE = "vertex"
    MAIN_API_JSON_NAME = "vertex.json"
    MAIN_API_TXT_NAME = "gemini_api.txt"
    MAIN_LOCATION = "global"
    MAIN_TOKEN_COUNT_ONLY = False
    MAIN_MAX_INPUT_TOKENS = 160000

    parser = argparse.ArgumentParser(description="Map selected Figure/Table IDs to extracted image files.")
    parser.add_argument("--classified-csv-path", default=None, help="Optional classified CSV path to use instead of the default lookup.")
    parser.add_argument("--include-excel-covered", action="store_true", help="Do not exclude rows already covered by Excel matching columns.")
    parser.add_argument("--exclude-excel-covered", action="store_true", help="Exclude rows already covered by Excel matching columns.")
    args = parser.parse_args()

    try:
        if MAIN_API_MODE == "vertex":
            api_key_path = find_api_key_file(MAIN_API_JSON_NAME)
            with open(api_key_path, "r", encoding="utf-8") as f:
                cred_data = json.load(f)

            main_project_id = cred_data.get("project_id")
            if not main_project_id:
                raise ValueError(f"서비스 계정 JSON에 project_id가 없습니다: {api_key_path}")
        else:
            main_project_id = None

        run_mapping_main(
            root_dir=ROOT_DIR,
            model_name=MAIN_MODEL_NAME,
            api_mode=MAIN_API_MODE,
            api_json_name=MAIN_API_JSON_NAME,
            api_txt_name=MAIN_API_TXT_NAME,
            project_id=main_project_id,
            location=MAIN_LOCATION,
            token_count_only=MAIN_TOKEN_COUNT_ONLY,
            max_input_tokens=MAIN_MAX_INPUT_TOKENS,
            classified_csv_path=args.classified_csv_path,
            exclude_excel_covered=args.exclude_excel_covered and not args.include_excel_covered,
        )
    except Exception as e:
        print(f"❌ 실행 실패: {e}")
