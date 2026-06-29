import json
import re
from pathlib import Path
from typing import List, Dict
import pandas as pd
from google.genai import types
import sys

# --- [경로 설정] 프로젝트 최상위 경로를 sys.path에 추가 ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from find_api import get_genai_client, find_api_key_file
from LLM_API import generate_content_with_guard, calculate_gemini_token_cost


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


# =========================
# 유틸
# =========================
def load_markdown_text(folder: Path) -> str:
    """
    논문 전체 markdown 본문을 하나의 텍스트로 만들어 LLM 프롬프트에 넣기 위한 함수
    01에서는 plain/text 로 주었지만 여기서는 프롬프트에 명시하려 하였음
    그냥 plain/text 로 주는게 더 나을듯 하긴 함
    """
    # 하위 폴더의 md 파일까지 모두 찾도록 rglob 사용
    md_files = sorted(folder.rglob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"Markdown 파일이 없습니다: {folder}")

    texts = []
    for md in md_files:
        try:
            texts.append(md.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            texts.append(md.read_text(encoding="utf-8", errors="replace"))

    full_text = "\n\n".join(texts)
    return full_text

def get_pdf_parts(folder: Path) -> list:
    """폴더 내의 모든 PDF 파일을 읽어 Gemini가 이해할 수 있는 Part 객체 리스트 (application/pdf)로 반환"""
    pdf_files = sorted(folder.rglob("*.pdf"))
    parts = []
    for pdf in pdf_files:
        with open(pdf, "rb") as f:
            parts.append(types.Part.from_bytes(data=f.read(), mime_type="application/pdf"))
    print("counted pdf",len(parts))
    return parts

def call_llm_api_json(
        client,
        model_name: str,
        prompt: str,
        document_parts: list,
        task_name: str,
        count_only: bool = False,
        mock_response=None,
) -> tuple[list, dict]:
    """
    JSON 응답을 기대하는 Gemini 호출 래퍼 함수
    count_only=True : 실제 생성은 안 하고 토큰 수와 예상 비용만 계산
    count_only=False : 실제 Gemini 호출
    - generate_content_with_guard 호출
    - json.loads(text) 파싱

    """
    if count_only:
        counted_tokens = None
        try:
            token_result = client.models.count_tokens(
                model=model_name,
                contents=document_parts + [prompt],
            )
            counted_tokens = getattr(token_result, "total_tokens", None)
            counted_tokens = int(counted_tokens) if counted_tokens is not None else None
        except Exception as e:
            print(f"      ! {task_name} count_tokens 실패: {e}")

        cost_info = None
        try:
            cost_info = calculate_gemini_token_cost(
                model_name=model_name,
                input_tokens=counted_tokens,
                output_tokens=0,
                total_tokens=counted_tokens,
            ) if counted_tokens is not None else None
        except Exception:
            cost_info = None

        usage = {
            "task_name": task_name,
            "model_name": model_name,
            "input_tokens": counted_tokens,
            "output_tokens": 0,
            "total_tokens": counted_tokens,
            "billed_output_tokens": 0,
            "count_only": True,
        }
        if cost_info:
            usage.update({
                "pricing_tier": cost_info.get("pricing_tier"),
                "input_rate_usd_per_1m": cost_info.get("input_rate_usd_per_1m"),
                "output_rate_usd_per_1m": cost_info.get("output_rate_usd_per_1m"),
                "cache_rate_usd_per_1m": cost_info.get("cache_rate_usd_per_1m"),
                "input_cost_usd": cost_info.get("input_cost_usd"),
                "output_cost_usd": cost_info.get("output_cost_usd"),
                "cache_cost_usd": cost_info.get("cache_cost_usd"),
                "total_cost_usd": cost_info.get("total_cost_usd"),
            })

        print(f"      · {task_name} count-only usage: {usage}")
        return (mock_response or []), usage

    result = generate_content_with_guard(
        client=client,
        model_name=model_name,
        contents=document_parts,
        prompt_text=prompt,
        task_name=task_name,
        rate_limiter=None,
        response_mime_type="application/json",
    )
    text = result.response_text.replace("```json", "").replace("```", "").strip()
    data = json.loads(text)
    if isinstance(data, dict) and "items" in data:
        data = data["items"]
    usage = result.to_usage_dict()
    usage["count_only"] = False
    print(f"      · {task_name} usage: {usage}")
    return data, usage


# =========================
# Gemini 일괄 분류 (Batch) - 프롬프트 개선 및 개수 추정 추가
# =========================
def classify_all_items_with_gemini(
        client,
        model_name: str,
        items_list: List[Dict],
        full_markdown: str,
        document_parts: list,
        count_only: bool = False,
) -> tuple[List[Dict], Dict]:
    """
        Args:
        client:
            Gemini API 호출에 사용할 클라이언트 객체.
        model_name:
            사용할 Gemini 모델명.
        items_list:
            평가할 figure/table 항목 리스트.
            각 원소는 보통 다음 정보를 포함한 dict이다:
            - item_id
            - item_type
            - base_id
            - is_supplementary
        full_markdown:
            논문 전체 markdown 텍스트.
            figure/table의 문맥, 캡션, 본문 설명 등을 함께 참고하기 위해 사용한다.
        document_parts:
            PDF 원본을 Gemini 입력용 Part 객체로 변환한 리스트.
            markdown만으로 부족한 시각적/원문 문맥을 보완하기 위해 사용한다.
        count_only:
            True이면 실제 분류 호출 없이 입력 토큰 수 및 예상 비용만 계산한다.
            False이면 Gemini를 실제 호출하여 item 분류 결과를 반환한다.

    Returns:
        tuple[List[Dict], Dict]:
            첫 번째 값: (중요)
                각 item에 대한 분류 결과 리스트.
                각 원소는 보통 다음 키를 포함한다:
                - item_id: 대상 figure/table ID
                - visual_type: 시각 자료 유형
                  (예: table, barplot, lineplot, heatmap, microscopy, schematic 등)
                - need_for_lnpdb: LNPDB 추출 필요 여부
                  ("yes", "no", "maybe")
                - priority: 추출 우선순위
                  ("high", "medium", "low")
                - estimated_data_count: 추출 가능 데이터 개수의 추정값
                  (정수 또는 짧은 문자열)
                - reason: 그렇게 판단한 짧은 근거 설명
                - confidence: 모델 판단 신뢰도
                  ("high", "medium", "low")

            두 번째 값:
                API 사용량 또는 count-only 실행 정보를 담은 dict.
                보통 다음 정보가 포함될 수 있다:
                - task_name
                - model_name
                - input_tokens
                - output_tokens
                - total_tokens
                - billed_output_tokens
                - count_only
                - total_cost_usd
    Notes:
        - 이 함수는 item들을 개별 호출하지 않고 한 번에 일괄 분류한다.
        - 429(쿼터 초과) 및 400(입력 과다) 오류에 대해 재시도/본문 절삭 로직이 포함되어 있다.
        - count_only=True일 때는 실제 분류 대신 fallback 결과가 반환될 수 있다.

    ### 프롬프트 자세히 설명 ###
    LNPDB에 필요한 경우
    - 개별 formulation 데이터가 있는 경우
    - 구체적 lipid 이름, 조성, molar ratio
    - 특정 개별 LNP에 대응되는 efficacy/transfection/biodistribution/screening 결과
    - 개별 formulation별 in vitro / in vivo numeric performance
    대체로 불필요한 경우
    - aggregated/grouped data
    - barplot 중에서 같은 head에 대해 평균냈다거나 하는 경우
    - lineplot 같은 집계형
    - graphical abstract
    - schematic
    - workflow
    - mechanism cartoon
    """
    items_json_str = json.dumps(items_list, indent=2, ensure_ascii=False) # 평가할 item 목록을 프롬프트에 넣기 좋게 JSON 문자열로 바꾸는 부분
    fallback_results = [{
        "item_id": str(x.get("item_id", "")).strip(),
        "visual_type": "unknown",
        "need_for_lnpdb": "maybe",
        "priority": "medium",
        "estimated_data_count": "unknown",
        "reason": "count_only_mode",
        "confidence": "low",
    } for x in items_list] # 가짜 기본 응답

    max_retries = 5 # 기본 재시도 회수
    base_wait = 15 # 실패시 기다릴 시간 : 429 에러
    current_markdown = full_markdown

    for attempt in range(max_retries):
        # 400 에러 대비 텍스트 절삭 (초기 500,000자 제한)
        max_len = 500000 // (2 ** attempt) if attempt > 0 else 500000
        if len(current_markdown) > max_len:
            if attempt > 0:
                print(f"      ! 토큰 초과 방지를 위해 본문 텍스트를 절삭합니다 ({len(current_markdown)}자 -> {max_len}자)")
            current_markdown = current_markdown[:max_len] + "\n...[Text Truncated]"

        prompt = f"""
You are reviewing a scientific paper for LNPDB curation.
I will provide the entire markdown text of the paper and a list of target items (figures/tables) found in it.

Your task is to classify whether EACH item in the list is needed for LNPDB extraction based on the paper's full context.
Treat Extended Data figures/tables as valid figure/table items. For example, 'extended data figure 1' and 'extended data table 1' should be classified in the same way as ordinary figures/tables, not ignored. Keep Extended Data items distinct from ordinary figures/tables and supplementary figures/tables.

[CRITICAL EXTRACTION CRITERIA]
LNPDB-relevant items MUST contain INDIVIDUAL formulation data:
- Specific LNP composition, exact lipid names, molar ratios.
- Delivery efficacy, transfection data, biodistribution, or screening results mapped to *specific individual* formulations.
- In-vitro / In-vivo numeric performance comparison of *specific* LNPs.

Usually NOT needed (Mark as 'no' or 'low' priority):
- ⚠️ AGGREGATED or GROUPED data (Barplots, Lineplots, etc.): Statistical summaries or grouped averages.
- graphical abstract, schematic, workflow diagram, conceptual illustration, mechanism cartoon.

Target items to evaluate:
{items_json_str}

Return JSON only. The output MUST be a JSON array of objects:
[
  {{
    "item_id": "string",
    "visual_type": "one of [table, barplot, lineplot, scatterplot, heatmap, microscopy, gel, western_blot, chemical_structure, schematic, workflow, illustration, graphical_abstract, mixed, unknown]",
    "need_for_lnpdb": "yes or no or maybe",
    "priority": "high or medium or low",
    "estimated_data_count": "integer or short string",
    "reason": "short reason based on the text",
    "confidence": "high or medium or low"
  }}
]

Here is the entire markdown text of the paper:
----------------
{current_markdown}
----------------
"""
        try:
            data, usage = call_llm_api_json(
                client=client,
                model_name=model_name,
                prompt=prompt,
                document_parts=document_parts,
                task_name="ft_selector_classify_all_items",
                count_only=count_only,
                mock_response=fallback_results,
            )

            if not isinstance(data, list):
                raise ValueError("LLM did not return a JSON array.")
            return data, usage

        except Exception as e:
            error_msg = str(e).lower()

            # 💡 [핵심] 에러 종류별 세분화 처리
            if "429" in error_msg or "resource_exhausted" in error_msg:
                if "per_day" in error_msg or "per day" in error_msg:
                    print(f"\n🚨 [치명적 에러] 일일 API 할당량(RPD)을 모두 소진했습니다. 작업을 중단합니다.")
                    import sys
                    sys.exit(1)
                elif "tokens_per_minute" in error_msg or "tokens" in error_msg:
                    wait_time = base_wait * (2 ** attempt) + 10
                    print(f"      ! [429 TPM 초과] 분당 토큰 한도도달. {wait_time}초 대기 후 재시도... ({attempt + 1}/{max_retries})")
                    import time
                    time.sleep(wait_time)
                    continue
                else:
                    wait_time = base_wait * (2 ** attempt)
                    print(f"      ! [429 RPM 초과] 분당 요청 횟수 초과. {wait_time}초 대기 후 재시도... ({attempt + 1}/{max_retries})")
                    import time
                    time.sleep(wait_time)

            elif "400" in error_msg or "invalid_argument" in error_msg:
                print(f"      ! [400 토큰 초과] 텍스트가 한도를 넘었습니다. 데이터를 절삭하고 재시도합니다. ({attempt + 1}/{max_retries})")
                continue
            else:
                print(f"\n⚠️ 기타 에러 발생: {e}")
                return [], {}

    print("      ❌ 최대 재시도 횟수 초과로 분류 실패")
    return [], {}


# =========================
# 메인 처리 1: 단일 폴더용
# =========================
def classify_fig_table_csv_for_lnpdb(
        target_folder,
        inventory_csv_name="fig_table_inventory.csv",
        output_csv_name="fig_table_lnpdb_classified.csv",
        model_name="gemini-3.1-pro-preview",
        api_mode="vertex",
        api_json_name="vertex.json",
        api_txt_name="gemini_api.txt",
        project=None,
        location="global",
        count_only: bool = False,
):
    folder = Path(target_folder)

    inventory_csv = folder / inventory_csv_name
    if not inventory_csv.exists():
        print(f"❌ 에러: 입력 CSV가 없습니다 ({inventory_csv})")
        return None

    # Vertex는 vertex-*.json 또는 지정 JSON을 사용하고, AI Studio는 gemini_api.txt를 사용
    if api_mode == "vertex":
        api_key_path = find_api_key_file(api_json_name) if api_json_name else find_api_key_file("vertex.json")
        with open(api_key_path, "r", encoding="utf-8") as f:
            cred_data = json.load(f)

        project_id = project or cred_data.get("project_id")
        if not project_id:
            raise ValueError(f"서비스 계정 JSON에 project_id가 없습니다: {api_key_path}")

        print(f"🔧 Vertex 프로젝트 설정: {project_id}")
        client = get_genai_client(
            mode="vertex",
            key_path=str(api_key_path),
            project=project_id,
            location=location,
        )
    elif api_mode == "aistudio":
        client = get_genai_client(
            mode="aistudio",
            filename=api_txt_name,
        )
    else:
        raise ValueError("api_mode는 'vertex' 또는 'aistudio' 여야 합니다.")

    df = pd.read_csv(inventory_csv)
    if "item_id" in df.columns:
        df["item_id"] = df["item_id"].apply(normalize_ft_item_id)
    if "base_id" in df.columns:
        df["base_id"] = df["base_id"].apply(normalize_ft_item_id)
    markdown_text = load_markdown_text(folder)
    pdf_parts = get_pdf_parts(folder)

    print(f"📂 처리 폴더: {folder}")
    print(f"📄 입력 CSV: {inventory_csv_name}")
    print(f"🧾 평가할 항목 수: {len(df)}개 (한 번의 API 호출로 처리합니다)")

    # 1. API에 보낼 항목 리스트 준비
    items_to_evaluate = []
    for _, row in df.iterrows():
        items_to_evaluate.append({
            "item_id": normalize_ft_item_id(row.get("item_id", "")),
            "item_type": str(row.get("item_type", "")).strip(),
            "base_id": normalize_ft_item_id(row.get("base_id", "")),
            "is_supplementary": bool(row.get("is_supplementary", False))
        })

    # 2. Gemini API 일괄 호출
    try:
        print("⏳ Gemini API 호출 중... (논문 전체 분석 중이므로 약간의 시간이 걸립니다)")
        api_results, usage_info = classify_all_items_with_gemini(
            client=client,
            model_name=model_name,
            items_list=items_to_evaluate,
            full_markdown=markdown_text,
            document_parts=pdf_parts,
            count_only=count_only,
        )
        print("✅ API 응답 완료!")
        if usage_info:
            usage_csv = folder / "fig_table_lnpdb_usage.csv"
            pd.DataFrame([usage_info]).to_csv(usage_csv, index=False, encoding="utf-8-sig")
            print(f"💾 usage 저장 완료: {usage_csv}")
    except Exception as e:
        print(f"❌ API 호출 실패: {e}")
        api_results = []
        usage_info = {}

    # 3. 결과 매핑
    if api_results:
        results_df = pd.DataFrame(api_results)
        if "item_id" in results_df.columns:
            results_df["item_id"] = results_df["item_id"].apply(normalize_ft_item_id)
        out_df = pd.merge(df, results_df, on="item_id", how="left")
    else:
        out_df = df.copy()
        for col in ["visual_type", "need_for_lnpdb", "priority", "estimated_data_count", "reason", "confidence"]:
            out_df[col] = "error"

    out_df["need_for_lnpdb"] = out_df["need_for_lnpdb"].fillna("maybe")
    out_df["priority"] = out_df["priority"].fillna("medium")
    out_df["visual_type"] = out_df["visual_type"].fillna("unknown")
    out_df["estimated_data_count"] = out_df["estimated_data_count"].fillna("unknown")

    # 4. 정렬 (yes > maybe > no)
    need_order = {"yes": 0, "maybe": 1, "no": 2}
    priority_order = {"high": 0, "medium": 1, "low": 2}

    out_df["_need_order"] = out_df["need_for_lnpdb"].map(need_order).fillna(9)
    out_df["_priority_order"] = out_df["priority"].map(priority_order).fillna(9)

    out_df = out_df.sort_values(
        by=["_need_order", "_priority_order", "item_type", "item_id"]
    ).drop(columns=["_need_order", "_priority_order"])

    # === 추가 시작 ===
    if "manual_select" not in out_df.columns:
        out_df["manual_select"] = ""

    # 맨 오른쪽으로 이동
    manual_col = out_df.pop("manual_select")
    out_df["manual_select"] = manual_col

    # 5. 저장
    output_csv = folder / output_csv_name
    out_df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 80)
    print(f"✅ 저장 완료: {output_csv}")
    print(out_df[["item_id", "visual_type", "need_for_lnpdb", "priority", "estimated_data_count"]].head(10))

    return out_df


# =========================
# 메인 처리 2: 다중 폴더용
# =========================
def process_all_subfolders_for_lnpdb_classification(
        root_folder,
        inventory_csv_name="fig_table_inventory.csv",
        output_csv_name="fig_table_lnpdb_classified.csv",
        model_name="gemini-3.1-pro-preview",
        api_mode="vertex",
        api_json_name="vertex.json",
        api_txt_name="gemini_api.txt",
        project=None,
        location="global",
        recursive=False,
        count_only: bool = False,
):
    root = Path(root_folder)

    if recursive:
        folders = sorted([p for p in root.rglob("*") if p.is_dir()])
    else:
        folders = sorted([p for p in root.iterdir() if p.is_dir()])

    print(f"📂 상위 폴더: {root}")
    print(f"📁 분석 대상 하위 폴더 수: {len(folders)}개")

    success = 0
    fail = 0
    skip = 0

    for i, folder in enumerate(folders, start=1):
        print("\n" + "=" * 80)
        print(f"[{i}/{len(folders)}] {folder.name} 폴더 처리 중...")

        inventory_csv = folder / inventory_csv_name
        md_files = list(folder.rglob("*.md"))  # 여기도 rglob 적용

        if not inventory_csv.exists() or not md_files:
            print(f"  ⚠️ 건너뜀: {inventory_csv_name} 또는 md 파일이 없습니다.")
            skip += 1
            continue

        try:
            classify_fig_table_csv_for_lnpdb(
                target_folder=folder,
                inventory_csv_name=inventory_csv_name,
                output_csv_name=output_csv_name,
                model_name=model_name,
                api_mode=api_mode,
                api_json_name=api_json_name,
                api_txt_name=api_txt_name,
                project=project,
                location=location,
                count_only=count_only,
            )
            success += 1
        except Exception as e:
            print(f"  ❌ 실패: {e}")
            fail += 1

    print("\n" + "=" * 80)
    print("🎯 전체 분류 작업 종료")
    print(f"✅ 성공: {success}개 폴더 | ❌ 실패: {fail}개 폴더 | ⏭️ 건너뜀: {skip}개 폴더")


# =========================
# 실행 블록
# =========================
if __name__ == "__main__":
    print("🚀 스크립트 실행 시작!")

    MODEL_NAME = "gemini-3.1-pro-preview" # gemini-3.1-pro-preview / gemini-2.5-flash /gemini-3.1-flash-lite-preview
    API_MODE = "vertex"  # "vertex" 또는 "aistudio"
    API_JSON_NAME = "vertex.json"
    API_TXT_NAME = "gemini_api.txt"
    PROJECT_ID = "avian-light-492007-c2"
    LOCATION = "global"
    COUNT_ONLY_MODE = False

    # ---------------------------------------------------------
    # 🔴 설정 구역 🔴
    # ---------------------------------------------------------
    SINGLE_FOLDER_MODE = True
    SINGLE_FOLDER = r"C:\Users\kogun\PycharmProjects\LNPDB_Articles_Extraction\Extraction_Examples\excel_o"  # 테스트할 폴더 경로 확인 요망

    MULTI_FOLDER_MODE = False
    ROOT_FOLDER = r"C:\Users\kogun\PycharmProjects\LNPDB_Articles_Extraction\Extraction_Examples\excel_o"
    RECURSIVE_SCAN = False
    # ---------------------------------------------------------

    if SINGLE_FOLDER_MODE:
        print("\n▶️ [단일 폴더 모드]를 시작합니다...")
        classify_fig_table_csv_for_lnpdb(
            target_folder=SINGLE_FOLDER,
            inventory_csv_name="fig_table_inventory.csv",
            output_csv_name="fig_table_lnpdb_classified.csv",
            model_name=MODEL_NAME,
            api_mode=API_MODE,
            api_json_name=API_JSON_NAME,
            api_txt_name=API_TXT_NAME,
            project=PROJECT_ID,
            location=LOCATION,
            count_only=COUNT_ONLY_MODE,
        )

    if MULTI_FOLDER_MODE:
        print("\n▶️ [다중 폴더(전체) 모드]를 시작합니다...")
        process_all_subfolders_for_lnpdb_classification(
            root_folder=ROOT_FOLDER,
            inventory_csv_name="fig_table_inventory.csv",
            output_csv_name="fig_table_lnpdb_classified.csv",
            model_name=MODEL_NAME,
            api_mode=API_MODE,
            api_json_name=API_JSON_NAME,
            api_txt_name=API_TXT_NAME,
            project=PROJECT_ID,
            location=LOCATION,
            recursive=RECURSIVE_SCAN,
            count_only=COUNT_ONLY_MODE,
        )

    print(f"count_only_mode={COUNT_ONLY_MODE}")

    if not SINGLE_FOLDER_MODE and not MULTI_FOLDER_MODE:
        print("⚠️ 모든 모드가 꺼져있습니다. 설정 구역에서 하나를 True로 변경해주세요.")
