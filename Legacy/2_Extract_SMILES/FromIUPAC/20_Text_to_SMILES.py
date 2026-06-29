import sys
import pandas as pd
from pathlib import Path

# --- [경로 설정] ---
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent 
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# API 유틸리티 및 두 개의 핵심 모듈 임포트
from find_api import find_api_key_file, get_vertexai_client
import Extract_Text_Lipid
import Extract_Lipid_SMILES
import json
# ==========================================
# 통합 파이프라인 실행 함수
# ==========================================
def run_integrated_text_to_smiles(folder_path_str, db_path_str):
    folder = Path(folder_path_str)
    db_path = Path(db_path_str)

    if not folder.exists():
        print(f"❌ 오류: 분석할 폴더를 찾을 수 없습니다 -> {folder}")
        return

    print("=" * 70)
    print(f"🚀 [텍스트 -> SMILES 통합 파이프라인] 시작")
    print(f"📂 대상 폴더: {folder.name}")
    print("=" * 70)

    # 1. API 클라이언트 초기화
    try:
        api_path = find_api_key_file("vertex.json")
        with open(api_path, "r", encoding="utf-8") as f:
            cred_data = json.load(f)

        project_id = cred_data.get("project_id")  # <- 원하는 프로젝트로 직접 지정
        client = get_vertexai_client(api_path, project=project_id)
    except Exception as e:
        print(f"❌ API 클라이언트 초기화 실패: {e}")
        return

    # ---------------------------------------------------------
    # [STEP 1] 마크다운에서 화합물 ID 및 IUPAC 명칭 추출
    # ---------------------------------------------------------
    try:
        Extract_Text_Lipid.run_text_lipid_pipeline(folder, client, model_name="gemini-3.1-pro-preview")
    except Exception as e:
        print(f"❌ 텍스트 기반 IUPAC 추출 중 오류 발생: {e}")
        return

    # ---------------------------------------------------------
    # [STEP 1.5] 데이터 규격 브릿지 연결
    # ---------------------------------------------------------
    # Extract_Text_Lipid의 결과물
    extracted_csv = folder / "text_extracted_iupac.csv"
    # Extract_Lipid_SMILES의 입력물
    standardized_csv = folder / "compound_inventory_standardized.csv"

    if extracted_csv.exists():
        print(f"\n▶ [데이터 연결] 추출된 IUPAC 결과를 SMILES 변환기 규격에 맞게 병합합니다...")
        try:
            df = pd.read_csv(extracted_csv)
            
            # Extract_Lipid_SMILES.py가 요구하는 'Novelty' 컬럼이 없으면 기본값으로 추가
            if 'Novelty' not in df.columns:
                df['Novelty'] = 'Unknown' 
                
            df.to_csv(standardized_csv, index=False, encoding='utf-8-sig')
            print(f"  ✅ 규격 변환 완료: {standardized_csv.name}")
        except Exception as e:
            print(f"❌ 데이터 규격 변환 중 오류 발생: {e}")
            return
    else:
        print(f"❌ 텍스트 추출에 실패하여 SMILES 변환을 진행할 수 없습니다.")
        return

    # ---------------------------------------------------------
    # [STEP 2] 추출된 IUPAC을 SMILES로 변환 (OPSIN, CIR, PubChem, LNPDB)
    # ---------------------------------------------------------
    print(f"\n▶ [SMILES 2단계] 다중 API 및 DB를 활용한 SMILES 변환 시작...")
    try:
        Extract_Lipid_SMILES.run_smiles_pipeline(folder, db_path)
    except Exception as e:
        print(f"❌ SMILES 변환 중 오류 발생: {e}")

    print("\n" + "=" * 70)
    print("🎉 텍스트 기반 화학 구조 추출 파이프라인이 모두 완료되었습니다!")
    print("=" * 70)


# ==========================================
# 실행부 (단독 테스트용)
# ==========================================
if __name__ == "__main__":
    # 🔴 분석할 논문 마크다운 파일이 들어있는 폴더 경로
    TARGET_PAPER_FOLDER = r"C:\Users\kogun\PycharmProjects\LNPDB_Articles_Extraction\Extraction_Examples\excel_o"
    
    # 🔴 참조할 기존 LNPDB CSV 파일 경로
    LNPDB_PATH = r"G:\내 드라이브\LNPDB (1).csv"

    run_integrated_text_to_smiles(TARGET_PAPER_FOLDER, LNPDB_PATH)