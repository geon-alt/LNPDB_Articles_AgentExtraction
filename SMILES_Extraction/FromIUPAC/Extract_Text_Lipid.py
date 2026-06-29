import os
import sys
import json
import pandas as pd
from pathlib import Path

# --- [경로 설정] ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent 
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# (단독 테스트용) API 로드 유틸리티
try:
    from find_api import find_api_key_file, get_vertexai_client
    from LLM_API import generate_content_with_guard
    from LLM_Batch import (
        build_generate_content_batch_request,
        build_batch_request_metadata,
        create_batch_request_file,
        create_batch_job_record,
        submit_batch_job,
        poll_batch_job,
        download_batch_results,
        load_batch_results_as_map,
        append_batch_request,
        count_requests_in_jsonl,
    )
except ImportError:
    pass


DEFAULT_GCS_BATCH_BUCKET = "gs://lnpdb-articles-extraction-batch-results-geon"


def _sanitize_request_token(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value)


def make_text_lipid_custom_id(folder: Path, md_path: Path) -> str:
    relative = md_path.relative_to(folder).with_suffix("").as_posix()
    return f"text_lipid__{_sanitize_request_token(relative)}"


def build_iupac_prompt(request_id: str) -> str:
    return f"""
당신은 화학 논문 데이터 구조화 전문가입니다.

request_id: {request_id}

제공된 텍스트(논문 본문 또는 Markdown)를 분석하여,
새롭게 합성되었거나 실험에 사용된 주요 화합물
(특히 ionizable lipid, helper lipid, PEG lipid, cholesterol 유도체 등)의
식별자와 IUPAC 이름을 추출하세요.

지시사항:
1. 화합물을 지칭하는 짧은 이름 또는 ID를 찾으세요.
   예: "Compound 1", "C8-494", "A1", "DOTAP", "DMG-PEG2000"
2. 해당 화합물의 IUPAC_name을 추출하세요.
   상용 지질 등으로 IUPAC이 본문에 없으면 "N/A"로 두세요.
3. Novelty는 다음 중 하나만 사용하세요:
   - "Novel": 이 논문에서 새롭게 설계/합성된 경우
   - "Commercial": 기존 상용 물질, 잘 알려진 대조군, 기존 물질인 경우
4. 반드시 JSON 객체만 반환하세요.
5. 최상위에 request_id를 그대로 포함하세요.

출력 형식:
{{
  "request_id": "{request_id}",
  "results": [
    {{
      "Name": "C8-494",
      "IUPAC_name": "Heptadecan-9-yl 8-((3-(2-hydroxyacetamido)...",
      "Novelty": "Novel"
    }},
    {{
      "Name": "DOTAP",
      "IUPAC_name": "N/A",
      "Novelty": "Commercial"
    }}
  ]
}}
"""


def parse_iupac_payload(text: str, expected_request_id: str) -> list[dict]:
    payload = json.loads(str(text or "").replace("```json", "").replace("```", "").strip())
    response_request_id = str(payload.get("request_id", "")).strip()
    if not response_request_id:
        raise ValueError("request_id missing in response payload")
    if response_request_id != expected_request_id:
        raise ValueError(f"request_id mismatch: expected={expected_request_id} | got={response_request_id}")
    results = payload.get("results", [])
    if not isinstance(results, list):
        raise ValueError("results must be a list")
    normalized = []
    for row in results:
        if not isinstance(row, dict):
            continue
        if not str(row.get("Name", "")).strip():
            continue
        if "IUPAC_name" not in row or "Novelty" not in row:
            continue
        normalized.append(row)
    if not normalized:
        raise ValueError("results missing required fields")
    return normalized

# ==========================================
# 실행부 (단독 테스트용)
# ==========================================
def extract_iupac_from_text(client, model_name, text_content, request_id: str = "sync_iupac"):
    max_retries = 5
    current_text = text_content

    for attempt in range(max_retries):
        max_chars = 200000 // (2 ** attempt) if attempt > 0 else 200000
        if len(current_text) > max_chars:
            current_text = current_text[:max_chars] + "\n...[Text Truncated]"

        prompt = build_iupac_prompt(request_id)
        try:
            call_result = generate_content_with_guard(
                client=client,
                model_name=model_name,
                contents=[current_text],
                prompt_text=prompt,
                task_name="extract_iupac_from_text",
                response_mime_type="application/json",
                max_retries=1,
            )
            return parse_iupac_payload(call_result.response_text, request_id)
        except Exception as e:
            error_msg = str(e).lower()
            if "400" in error_msg or "invalid_argument" in error_msg:
                continue
            print(f"! 경고: 참조할 LNPDB 파일이 없습니다: {e}")
            return []

    print("      !! 최대 재시도 횟수 초과로 추출 실패")
    return []


def run_text_lipid_batch(folder: Path, client, model_name: str, md_payloads: list[dict]):
    request_file = create_batch_request_file(folder, f"text_lipid_{folder.name}")
    for item in md_payloads:
        custom_id = item["custom_id"]
        metadata = build_batch_request_metadata(
            task_name="text_lipid_iupac",
            model_name=model_name,
            custom_id=custom_id,
            stage_name="text_lipid_iupac",
            item_id=item["md_path"].name,
            paper_folder=str(folder),
        )
        request_body = build_generate_content_batch_request(
            model_name=model_name,
            contents=[item["content"]],
            prompt_text=build_iupac_prompt(custom_id),
            response_mime_type="application/json",
        )
        append_batch_request(request_file=request_file, custom_id=custom_id, request_body=request_body, metadata=metadata)

    local_job_id = create_batch_job_record(
        paper_folder=folder,
        task_name="text_lipid_iupac",
        model_name=model_name,
        request_file=request_file,
        metadata={
            "request_count": count_requests_in_jsonl(request_file),
            "gcs_input_uri": f"{DEFAULT_GCS_BATCH_BUCKET}/batch/{request_file.name}",
            "gcs_output_uri_prefix": f"{DEFAULT_GCS_BATCH_BUCKET}/batch_output/{request_file.stem}",
        },
    )
    batch_job = submit_batch_job(client=client, paper_folder=folder, local_job_id=local_job_id, display_name=f"text-lipid-{folder.name}")
    print(f"  🚀 batch 제출 완료: {batch_job.name}")
    finished_job = poll_batch_job(client=client, paper_folder=folder, local_job_id=local_job_id, poll_interval_seconds=30)
    state_name = getattr(getattr(finished_job, "state", None), "name", None) or str(getattr(finished_job, "state", "UNKNOWN"))
    print(f"  📌 batch 종료 상태: {state_name}")
    if state_name != "JOB_STATE_SUCCEEDED":
        raise RuntimeError(f"text_lipid_iupac batch ?ㅽ뙣: {state_name}")
    result_file = download_batch_results(client=client, paper_folder=folder, local_job_id=local_job_id)
    return load_batch_results_as_map(result_file)


def run_text_lipid_pipeline(folder: Path, client, model_name="gemini-3.1-pro-preview", output_csv_path=None):
    print(f"\n🚀 [SMILES 1단계] 텍스트 본문(Markdown) 기반 IUPAC 명칭 추출 시작: {folder.name}")
    md_files = list(folder.glob("**/*.md"))
    if not md_files:
        print("  ! 경고: 분석할 마크다운(.md) 파일이 없습니다.")
        return

    md_payloads = []
    for md_file in md_files:
        with open(md_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if len(content.strip()) < 50:
            continue
        md_payloads.append({"md_path": md_file, "content": content, "custom_id": make_text_lipid_custom_id(folder, md_file)})

    if not md_payloads:
        print("  ! 추출된 IUPAC 정보가 없어 CSV를 생성하지 않습니다.")
        return

    all_extracted_data = []
    failed_items: list[dict] = []
    results_map = run_text_lipid_batch(folder, client, model_name, md_payloads)

    for item in md_payloads:
        row = results_map.get(item["custom_id"])
        if not row or not row.get("success"):
            failed_items.append(item)
            continue
        response_text = str(row.get("response_text", "")).strip()
        if not response_text:
            failed_items.append(item)
            continue
        try:
            records = parse_iupac_payload(response_text, item["custom_id"])
        except Exception:
            failed_items.append(item)
            continue
        all_extracted_data.extend(records)

    if failed_items:
        print(f"  ! batch 실패된 markdown {len(failed_items)}개 sync retry")
        for item in failed_items:
            records = extract_iupac_from_text(client, model_name, item["content"], item["custom_id"])
            if records:
                all_extracted_data.extend(records)

    if all_extracted_data:
        output_csv_path = Path(output_csv_path) if output_csv_path is not None else folder / "text_extracted_iupac.csv"
        pd.DataFrame(all_extracted_data).to_csv(output_csv_path, index=False, encoding="utf-8-sig")
        print(f"  텍스트 기반 추출 저장: {output_csv_path}")
        print("  텍스트 기반 추출 완료.")
    else:
        print("  ! 추출된 IUPAC 정보가 없어 CSV를 생성하지 않습니다.")


if __name__ == "__main__":
    TEST_FOLDER = Path(r"/Users/kogeon/Library/CloudStorage/GoogleDrive-geon@molcube.com/내 드라이브/EXTRACT-TEST/BEND-test")
    API_JSON_NAME = "vertex.json"

    try:
        api_key_path = find_api_key_file(API_JSON_NAME)

        with open(api_key_path, "r", encoding="utf-8") as f:
            cred_data = json.load(f)

        project_id = cred_data.get("project_id")
        if not project_id:
            raise ValueError(f"서비스 계정 JSON에 project_id가 없습니다: {api_key_path}")

        print(f"🔧 Vertex 프로젝트 설정: {project_id}")
        test_client = get_vertexai_client(api_key_path, project=project_id)

        if TEST_FOLDER.exists():
            run_text_lipid_pipeline(TEST_FOLDER, test_client)
        else:
            print(f"❌ 폴더 경로를 찾을 수 없습니다: {TEST_FOLDER}")
            
    except Exception as e:
        print(f"❌ 단독 실행 중 오류 발생: {e}")
