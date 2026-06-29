import json
import re
from pathlib import Path
from collections import defaultdict
import pandas as pd
import sys

# --- [경로 설정] 프로젝트 최상위 경로를 sys.path에 추가 ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from google.genai import types
from LLM_API import generate_content_with_guard
from find_api import get_genai_client


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


def count_total_input_tokens(client, model_name, document_parts, prompt):
    """
    gemini 호출 전 input 토큰 수 계산 요청을 보냄
    """
    try:
        result = client.models.count_tokens(
            model=model_name,
            contents=document_parts + [prompt],
        )
        total_tokens = getattr(result, "total_tokens", None)
        return int(total_tokens) if total_tokens is not None else None
    except Exception as e:
        print(f"      ! count_tokens 실패: {e}")
        return None


def get_document_part(file_path: Path):
    """파일을 Gemini 입력 파트로 :
    - markdown 형식을 text로 읽도록 함 (text/plain)
    - 그 외는 pdf 로 읽도록 함 (application/pdf)
    """
    mime_type = "text/plain" if file_path.suffix.lower() == ".md" else "application/pdf"
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    return types.Part.from_bytes(data=file_bytes, mime_type=mime_type)


def filter_hierarchy(items):
    """
    상위 figure/table ID를 제거하고 더 구체적인 하위 ID만 남기는 후처리
    figure 2, figure 2a, figure 2b
    이렇게 있을시에 figure 2를 제거함
    """
    items = sorted(list(set(normalize_ft_item_id(i) for i in items if str(i).strip()))) # 소문자 정규화 및 정렬
    items_to_keep = set(items) #집합으로

    for item in items:
        has_children = any(
            other.startswith(item) # item 으로 시작되는 문자열 있을시 True / 자식 문자열은 부모 문자열로 시작함 fig2, fig2a
            and len(other) > len(item) #  중복 제거
            and other[len(item):].isalpha() # item 뒤에 붙은 것이 알파벳인가 : 자식이면 item 뒤에 붙은 것이 알파벳임
            for other in items # 리스트 컴프리헨션 비슷한 계열
        ) # 세 조건이 모두 충족해야 True 가 나오며, for 로 인해 하나라도 True가 나오면 자식이 있음
        if has_children: # 자식을 가지고 있으면 버려라
            items_to_keep.discard(item)

    return sorted(items_to_keep)


def group_by_base_figure(items):
    """
    item들을 base figure/table 기준으로 그룹화
    figure 2a, figure 2b 등을 base figure 2 에 할당
    """
    groups = defaultdict(list)
    for item in items:
        # 일반적인 형식을 따르는 문자열로부터 부모 base를 알아냄 : figure 2a -> match = figure 2
        match = re.match(r"^((supplementary|extended\s+data)\s+)?(figure|fig|table)\s+[a-zA-Z]?\d+", item, re.I) # 정규식에 포함되면 True
        if match: # 정규식에 해당하는 key의 list 에 추가
            base_name = match.group(0).strip().lower()
            groups[base_name].append(item)
        else: # 가끔 일반적인 형식을 따르지 않는 경우 개별 저장
            groups[item].append(item)
    return dict(groups)


def classify_item(item_id: str):
    """item이 figure인지 table인지"""
    s = item_id.lower().strip()
    if "table" in s:
        return "table"
    if "fig" in s or "figure" in s:
        return "figure"
    return "unknown"


def is_supplementary(item_id: str):
    """
    item이 supplementary인지
    """
    s = item_id.lower().strip()
    return (
        "supplementary" in s
        or re.search(r"\bfigure\s+s\d+", s) is not None
        or re.search(r"\bfig\s+s\d+", s) is not None
        or re.search(r"\btable\s+s\d+", s) is not None
    )


def get_unified_inventory(client, model_name, document_parts, max_input_tokens=200000):
    """
    Markdown/PDF 문서 전체를 대상으로 Gemini를 호출하여
    figure/table identifier 목록을 통합 추출한다.

    Args:
        client:
            Gemini API 호출에 사용할 클라이언트 객체 (vertex or google ai devlopers)
        model_name:
            사용할 Gemini 모델명
        document_parts:
            Markdown/PDF 문서를 Gemini 입력용 Part 객체로 변환한 리스트
        max_input_tokens:
            허용할 최대 입력 토큰 수
            초과 시 실제 LLM 호출 없이 빈 리스트를 반환한다

    Returns:
        list[str]:
            표준화된 figure/table identifier 목록
            예:
            - "figure 1"
            - "figure 2a"
            - "table s2"

            다음 경우 빈 리스트를 반환할 수 있다:
            - 입력 토큰 수 초과
            - 400/INVALID_ARGUMENT
            - 최대 재시도 초과
            - 기타 API 오류

    Notes:
        - 호출 전 count_total_input_tokens()로 입력 토큰 수를 점검한다.
        - generate_content_with_guard()를 사용해 JSON 응답을 요청한다.
        - 응답의 code fence를 제거한 뒤 JSON 파싱한다.
        - 429/RESOURCE_EXHAUSTED는 exponential backoff로 재시도한다.
    """
    prompt = """
Identify all Figure and Table IDs mentioned across these documents (Markdown and PDF).

Rules:
1. Find all figure/table identifiers mentioned in the documents.
2. Standardize to lowercase forms such as:
   - "figure 1"
   - "figure 2a"
   - "table 1"
   - "table s2"
   - "supplementary figure 3"
   - "extended data figure 1"
   - "extended data figure 5a"
   - "extended data table 1"
   Treat Extended Data figures/tables as valid identifiers and keep them distinct from ordinary and supplementary items.
3. Expand ranges:
   - "Fig. 2c-e" -> "figure 2c", "figure 2d", "figure 2e"
4. Remove duplicates.
5. Return only figure/table identifiers, no captions, no summaries.

Return JSON only:
{
  "items": [
    "figure 1",
    "figure 2a",
    "table 1",
    "table s2",
    "supplementary figure 3",
    "extended data figure 1",
    "extended data table 1"
  ]
}
"""
    counted_input_tokens = count_total_input_tokens(client, model_name, document_parts, prompt)
    if counted_input_tokens is not None:
        print(f"      · counted_input_tokens: {counted_input_tokens:,}")
        if counted_input_tokens > max_input_tokens:
            print(
                f"      ! 입력 토큰 제한 초과: {counted_input_tokens:,} > {max_input_tokens:,}. 추출을 건너뜁니다."
            )
            return []

    max_retries = 5
    base_wait = 15 # 멀티모달 처리는 무거우므로 기본 대기 시간을 15초로 길게 잡습니다.

    for attempt in range(max_retries):
        try:
            result = generate_content_with_guard(
                client=client,
                model_name=model_name,
                contents=document_parts,
                prompt_text=prompt,
                task_name="make_ft_csv_inventory",
                rate_limiter=None,
                response_mime_type="application/json",
            )

            text = result.response_text.replace("```json", "").replace("```", "").strip()
            print(f"      · token usage: {result.to_usage_dict()}")
            data = json.loads(text)
            return data.get("items", [])

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                wait_time = base_wait * (2 ** attempt) # 15초, 30초, 60초...
                print(f"      ! [429 쿼터 초과] {wait_time}초 대기 후 재시도 중... ({attempt + 1}/{max_retries})")
                import time
                time.sleep(wait_time)
            elif "400" in error_msg or "INVALID_ARGUMENT" in error_msg:
                print(f"      ! [400 토큰 초과] 문서 크기가 컨텍스트 제한을 초과했습니다. 추출을 건너뜁니다.")
                return [] # PDF는 부분 절삭이 어려우므로 안전하게 포기
            else:
                print(f"      ! 알 수 없는 API 에러 발생: {e}")
                return []

    print("      ! 최대 재시도 횟수 초과로 추출 실패")
    return []


def collect_document_files(folder: Path):
    """
     실제 처리할 문서 파일 고르기
    .md, .pdf
    """
    allowed_extensions = {".md", ".pdf"}
    return sorted(
        [
            f for f in folder.iterdir()
            if f.is_file()
            and f.suffix.lower() in allowed_extensions
            and not f.name.startswith("~")
        ]
    )


def extract_fig_table_only_from_folder(
    folder,
    client,
    model_name="gemini-3.1-pro-preview",
    output_csv_name="fig_table_inventory.csv",
    max_input_tokens=200000,
    token_count_only=False,
):
    """
    폴더 1개를 처리하는 실제 메인 함수
    - collect_document_files(folder)로 .md / .pdf 파일 목록을 모읍니다.
    - get_document_part(f)로 바꿔 document_parts 리스트 생성
    - token_count_only=True이면: 실제 추출은 하지 않고 프리뷰 프롬프트를 사용해 토큰만 계산
    - raw_items = get_unified_inventory(...) 으로 llm 을 통해 figure / table 리스트 만들기
    - clean_items = filter_hierarchy(raw_items) 으로 figure에 하위 분류 존재시 하위 분류만 남기기 : fig2, fig2a, fig2b 있을시 fig2 제거
    - grouped = group_by_base_figure(clean_items) 으로 하위 분류를 상위분류안에 넣가 fig2 에 fig2a, 2b 넣기
    """
    folder = Path(folder)
    document_files = collect_document_files(folder)

    if not document_files:
        print(f"  ⚠️ 건너뜀: 문서(.md/.pdf) 없음 -> {folder}")
        return None

    print(f"\n📂 처리 중: {folder}")
    print(f"   - 문서 수: {len(document_files)}")

    document_parts = [get_document_part(f) for f in document_files]

    if token_count_only:
        preview_prompt = """
Identify all Figure and Table IDs mentioned across these documents (Markdown and PDF).

Rules:
1. Find all figure/table identifiers mentioned in the documents.
2. Standardize to lowercase forms such as:
   - "figure 1"
   - "figure 2a"
   - "table 1"
   - "table s2"
   - "supplementary figure 3"
   - "extended data figure 1"
   - "extended data figure 5a"
   - "extended data table 1"
   Treat Extended Data figures/tables as valid identifiers and keep them distinct from ordinary and supplementary items.
3. Expand ranges:
   - "Fig. 2c-e" -> "figure 2c", "figure 2d", "figure 2e"
4. Remove duplicates.
5. Return only figure/table identifiers, no captions, no summaries.

Return JSON only:
{
  "items": [
    "figure 1",
    "figure 2a",
    "table 1",
    "table s2",
    "supplementary figure 3",
    "extended data figure 1",
    "extended data table 1"
  ]
}
"""
        counted_input_tokens = count_total_input_tokens(client, model_name, document_parts, preview_prompt)
        if counted_input_tokens is not None:
            print(f"  🔢 토큰 계산 전용 모드")
            print(f"  - counted_input_tokens: {counted_input_tokens:,}")
            print(f"  - max_input_tokens: {max_input_tokens:,}")
            print(f"  - 초과 여부: {counted_input_tokens > max_input_tokens}")
        else:
            print("  ! 토큰 계산 실패")

        return pd.DataFrame([
            {
                "folder": str(folder),
                "model_name": model_name,
                "counted_input_tokens": counted_input_tokens,
                "max_input_tokens": max_input_tokens,
                "is_over_limit": (counted_input_tokens > max_input_tokens) if counted_input_tokens is not None else None,
            }
        ])

    try:
        raw_items = [
            normalize_ft_item_id(x)
            for x in get_unified_inventory(client, model_name, document_parts, max_input_tokens=max_input_tokens)
        ]
        clean_items = filter_hierarchy(raw_items)
        grouped = group_by_base_figure(clean_items)

        rows = []
        for base_id, item_list in grouped.items():
            for item in sorted(item_list):
                rows.append(
                    {
                        "item_id": item,
                        "item_type": classify_item(item),
                        "base_id": base_id,
                        "is_supplementary": is_supplementary(item),
                    }
                )

        df = pd.DataFrame(rows)

        if df.empty:
            df = pd.DataFrame(columns=["item_id", "item_type", "base_id", "is_supplementary"])
        else:
            df = df.sort_values(["item_type", "base_id", "item_id"]).reset_index(drop=True)

        output_csv = folder / output_csv_name
        df.to_csv(output_csv, index=False, encoding="utf-8-sig")

        print(f"  ✅ 저장 완료: {output_csv}")
        print(f"  - 추출 개수: {len(df)}")
        return df

    except Exception as e:
        print(f"  ❌ 실패: {folder}")
        print(f"  에러: {e}")
        return None


def process_single_folder(
    target_folder,
    model_name="gemini-3.1-pro-preview",
    api_mode="vertex",
    api_json_name="vertex-490605-8d0be916872a.json",
    api_txt_name="gemini_api.txt",
    project="vertex-490605",
    location="global",
    max_input_tokens=200000,
    token_count_only=False,
):
    """폴더 하나만 처리하기 위한 래퍼, API client 생성"""
    target_folder = Path(target_folder)
    # Vertex는 vertex-*.json 자동 탐색, AI Studio는 gemini_api.txt 고정 탐색
    if api_mode == "vertex":
        client = get_genai_client(
            mode="vertex",
            key_path=api_json_name if api_json_name else None,
            project=project,
            location=location,
        )
    elif api_mode == "aistudio":
        client = get_genai_client(
            mode="aistudio",
            filename=api_txt_name,
        )
    else:
        raise ValueError("api_mode는 'vertex' 또는 'aistudio' 여야 합니다.")

    return extract_fig_table_only_from_folder(
        folder=target_folder,
        client=client,
        model_name=model_name,
        max_input_tokens=max_input_tokens,
        token_count_only=token_count_only,
    )


def process_all_subfolders(
    root_folder,
    model_name="gemini-3.1-pro-preview",
    api_mode="vertex",
    api_json_name="vertex-490605-8d0be916872a.json",
    api_txt_name="gemini_api.txt",
    project="vertex-490605",
    location="global",
    recursive=False,
    max_input_tokens=200000,
    token_count_only=False,
):
    root_folder = Path(root_folder)
    # Vertex는 vertex-*.json 자동 탐색, AI Studio는 gemini_api.txt 고정 탐색
    if api_mode == "vertex":
        client = get_genai_client(
            mode="vertex",
            key_path=api_json_name if api_json_name else None,
            project=project,
            location=location,
        )
    elif api_mode == "aistudio":
        client = get_genai_client(
            mode="aistudio",
            filename=api_txt_name,
        )
    else:
        raise ValueError("api_mode는 'vertex' 또는 'aistudio' 여야 합니다.")

    if recursive:
        subfolders = sorted([p for p in root_folder.rglob("*") if p.is_dir()])
    else:
        subfolders = sorted([p for p in root_folder.iterdir() if p.is_dir()])

    print(f"📂 상위 폴더: {root_folder}")
    print(f"📁 대상 하위 폴더 수: {len(subfolders)}")

    success_count = 0
    fail_count = 0
    skip_count = 0

    for i, folder in enumerate(subfolders, start=1):
        print("\n" + "=" * 80)
        print(f"[{i}/{len(subfolders)}] {folder.relative_to(root_folder)}")

        result = extract_fig_table_only_from_folder(
            folder=folder,
            client=client,
            model_name=model_name,
            max_input_tokens=max_input_tokens,
            token_count_only=token_count_only,
        )

        if result is None:
            # 문서 없음인지 실패인지 구분
            document_files = collect_document_files(folder)
            if not document_files:
                skip_count += 1
            else:
                fail_count += 1
        else:
            success_count += 1

    print("\n" + "=" * 80)
    print("✅ 전체 작업 완료")
    print(f"성공: {success_count}")
    print(f"실패: {fail_count}")
    print(f"건너뜀(문서 없음): {skip_count}")


if __name__ == "__main__":
    # =========================
    # 1) 한 폴더만 처리
    # =========================
    SINGLE_FOLDER_MODE = True
    SINGLE_FOLDER = r"/Users/kogeon/python_projects_path/LNPDB_Articles_Extraction/Extraction_Examples/excel_o"
    #C:\Users\kogun\PycharmProjects\LNPDB_Articles_Extraction\Extraction_Examples\excel_o

    # =========================
    # 2) 상위 폴더 아래 하위 폴더들 처리
    # =========================
    MULTI_FOLDER_MODE = False
    ROOT_FOLDER = r"G:\내 드라이브\EXTRACT-TEST"
    RECURSIVE_SCAN = False   # True면 모든 하위폴더 재귀 스캔

    MODEL_NAME = "gemini-3.1-pro-preview" # gemini-2.5-flash / gemini-3.1-pro-preview / gemini-3.1-flash-lite-preview
    API_MODE = "vertex"  # "vertex" 또는 "aistudio"
    API_JSON_NAME = "vertex.json"
    API_TXT_NAME = "gemini_api.txt"
    PROJECT_ID = "avian-light-492007-c2"
    LOCATION = "global"

    MAX_INPUT_TOKENS = 200000
    # True면 실제 API 생성 호출 없이 입력 토큰만 계산
    TOKEN_COUNT_ONLY = False

    if SINGLE_FOLDER_MODE:
        process_single_folder(
            target_folder=SINGLE_FOLDER,
            model_name=MODEL_NAME,
            api_mode=API_MODE,
            api_json_name=API_JSON_NAME,
            api_txt_name=API_TXT_NAME,
            project=PROJECT_ID,
            location=LOCATION,
            max_input_tokens=MAX_INPUT_TOKENS,
            token_count_only=TOKEN_COUNT_ONLY,
        )

    if MULTI_FOLDER_MODE:
        process_all_subfolders(
            root_folder=ROOT_FOLDER,
            model_name=MODEL_NAME,
            api_mode=API_MODE,
            api_json_name=API_JSON_NAME,
            api_txt_name=API_TXT_NAME,
            project=PROJECT_ID,
            location=LOCATION,
            recursive=RECURSIVE_SCAN,
            max_input_tokens=MAX_INPUT_TOKENS,
            token_count_only=TOKEN_COUNT_ONLY,
        )

# 2개 pdf / 45 페이지 0.151266 달러  : 'input_tokens': 18663, 'output_tokens': 1412, 'total_tokens': 28158
