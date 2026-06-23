import os
import sys
from pathlib import Path

# 상위 폴더(LNPDB_Articles_Extraction)를 모듈 검색 경로에 추가하여 find_api.py를 import
current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
sys.path.append(str(parent_dir))

from find_api import find_api_key_file, get_vertexai_client
from Extract_from_PDF_grouped import process_single_paper, get_dynamic_schema_from_db

# 💡 함수가 client를 받을 수 있도록 파라미터 업데이트
def run_batch_extraction(local_dir_path, gdrive_dir_path, db_csv_path, target_columns, model_name, client):
    local_parent_dir = Path(local_dir_path)
    gdrive_parent_dir = Path(gdrive_dir_path)
    db_path = Path(db_csv_path)

    print("동적 스키마를 초기화합니다...")
    dynamic_schema = get_dynamic_schema_from_db(str(db_path), target_columns)

    if not local_parent_dir.exists():
        print(f"오류: 로컬 최상위 폴더를 찾을 수 없습니다 -> {local_parent_dir}")
        return
        
    paper_folders = [f for f in local_parent_dir.iterdir() if f.is_dir() and not f.name.startswith('.')]
    print(f"\n총 {len(paper_folders)}개의 논문 폴더를 감지했습니다.\n" + "="*50)

    for i, paper_folder in enumerate(paper_folders, 1):
        target_csv_path = gdrive_parent_dir / paper_folder.name / f"{paper_folder.name}_metadata.csv"
        
        if target_csv_path.exists():
            print(f"\n▶ [{i}/{len(paper_folders)}] ⏭️ [SKIP] 이미 분석 완료된 폴더입니다: {paper_folder.name}")
            continue

        print(f"\n▶ [{i}/{len(paper_folders)}] 처리 시작: {paper_folder.name}")
        try:
            # 💡 process_single_paper에 client 전달
            process_single_paper(
                local_folder=paper_folder, 
                gdrive_base_folder=gdrive_parent_dir, 
                client=client, 
                model_name=model_name,
                dynamic_schema=dynamic_schema
            )
        except Exception as e:
            print(f"  !! {paper_folder.name} 폴더 처리 중 오류 발생: {e}")
            
    print("\n🎉 모든 논문 폴더의 분석 및 구글 드라이브 저장이 완료되었습니다!")

# ==========================================
# 실행부 
# ==========================================
if __name__ == "__main__":
    try:
        api_file_path = find_api_key_file("vertex-490605-8d0be916872a.json") 
        vertex_client = get_vertexai_client(api_file_path)
        print("✅ Vertex AI 클라이언트 초기화 완료")
    except Exception as e:
        print(f"❌ API 키 로드 실패: {e}")
        sys.exit(1)
    
    MY_LOCAL_DIR = r"/Users/kogeon/Library/CloudStorage/GoogleDrive-geon@molcube.com/내 드라이브/ATLAS_only_DOIs"
    MY_GDRIVE_DIR = r"/Users/kogeon/Library/CloudStorage/GoogleDrive-geon@molcube.com/내 드라이브/ATLAS_only_DOIs"
    MY_DB_PATH = r"/Users/kogeon/python_projects_path/LNPDB_extend/ATLAS_LNPDB/LNPDB.csv"
    
    LNPDB_COLS = [
        "Aqueous_buffer", "Dialysis_buffer", "Mixing_method",
        "Model", "Model_type", "Model_target",
        "Route_of_administration", "Cargo", "Cargo_type", "Dose_ug_nucleicacid",
        "Experiment_method", "Experiment_batching"
    ]
    
    SELECTED_MODEL = "gemini-3.1-pro-preview"

    run_batch_extraction(
        local_dir_path=MY_LOCAL_DIR,
        gdrive_dir_path=MY_GDRIVE_DIR,
        db_csv_path=MY_DB_PATH,
        target_columns=LNPDB_COLS,
        model_name=SELECTED_MODEL,
        client=vertex_client
    )