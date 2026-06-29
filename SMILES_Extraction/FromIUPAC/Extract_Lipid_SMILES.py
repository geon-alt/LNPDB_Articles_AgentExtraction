import pandas as pd
import subprocess
import requests
import urllib.parse
import time
import sys
from pathlib import Path

# --- [경로 설정] ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent 
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ==========================================
# 0. LNPDB 레퍼런스 로드 유틸리티
# ==========================================
def build_lnpdb_reference(db_path: Path):
    """기존 LNPDB CSV에서 Name -> SMILES 매핑 딕셔너리를 생성합니다."""
    ref_dict = {}
    if not db_path.exists():
        print(f"  ! 경고: 참조할 LNPDB 파일이 없습니다 ({db_path.name})")
        return ref_dict

    try:
        # LNPDB 로드
        df = pd.read_csv(db_path, low_memory=False)
        
        # 기존 DB의 (이름 컬럼, SMILES 컬럼) 쌍 지정
        # 실제 LNPDB 컬럼명에 맞춰 추가/수정 가능합니다.
        column_pairs = [
            ('IL_name', 'IL_SMILES'),
            ('HL_name', 'HL_SMILES'),
            ('PEG_name', 'PEG_SMILES'),
            ('CHL_name', 'CHL_SMILES'),
            ('Name', 'SMILES') # 일반적인 명칭
        ]

        for n_col, s_col in column_pairs:
            if n_col in df.columns and s_col in df.columns:
                for _, row in df.dropna(subset=[n_col, s_col]).iterrows():
                    name_key = str(row[n_col]).strip().lower()
                    smiles_val = str(row[s_col]).strip()
                    if name_key and smiles_val and smiles_val != "n/a" and smiles_val != "nan":
                        ref_dict[name_key] = smiles_val
                        
        print(f"  - 기존 LNPDB에서 {len(ref_dict)}개의 화합물 SMILES 레퍼런스를 로드했습니다.")
    except Exception as e:
        print(f"  ! LNPDB 로드 중 에러: {e}")
        
    return ref_dict

# ==========================================
# 1. SMILES 추출 도구 함수들 (안정성 강화)
# ==========================================
def get_smiles_opsin(identifier, opsin_path):
    try:
        result = subprocess.run(
            ["java", "-jar", str(opsin_path)],
            input=str(identifier),
            text=True,
            capture_output=True,
            check=True
        )
        smiles = result.stdout.strip()
        return smiles if smiles else None
    except Exception:
        return None

def fetch_with_retry(url, timeout=10, max_retries=3):
    """공공 API의 Rate Limit(429) 및 Timeout 대응"""
    import requests
    import time
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=timeout)
            if response.status_code == 200:
                return response
            elif response.status_code == 429: # Too Many Requests
                time.sleep(2 * (attempt + 1))
            else:
                return None
        except requests.exceptions.RequestException:
            time.sleep(2 * (attempt + 1))
    return None

def get_smiles_cir(identifier):
    try:
        encoded_id = urllib.parse.quote(identifier)
        url = f"https://cactus.nci.nih.gov/chemical/structure/{encoded_id}/smiles"
        response = fetch_with_retry(url)
        if response:
            return response.text.strip()
    except Exception:
        pass
    return None

def get_smiles_pubchem(identifier):
    try:
        encoded_id = urllib.parse.quote(identifier)
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{encoded_id}/property/IsomericSMILES/JSON"
        response = fetch_with_retry(url)
        if response:
            data = response.json()
            return data['PropertyTable']['Properties'][0]['IsomericSMILES']
    except Exception:
        pass
    return None

# ==========================================
# 2. 통합 순차 추출 로직 (Fallback)
# ==========================================
def resolve_smiles(row, opsin_path, lnpdb_ref):
    name = str(row.get('Name', '')).strip()
    iupac = str(row.get('IUPAC_name', '')).strip()
    novelty = str(row.get('Novelty', '')).strip()
    
    # 0단계: Novel이 아닌 경우, 기존 LNPDB에서 Name 기준으로 우선 탐색
    if novelty.lower() != "novel" and name.lower() in lnpdb_ref:
        return lnpdb_ref[name.lower()], "LNPDB DB (Name)"

    # 1단계: IUPAC이 존재하는 경우 순차 탐색
    if iupac and iupac != "N/A" and iupac != "nan":
        smiles = get_smiles_opsin(iupac, opsin_path)
        if smiles: return smiles, "OPSIN (IUPAC)"
        
        smiles = get_smiles_cir(iupac)
        if smiles: return smiles, "CIR (IUPAC)"
        
        time.sleep(0.5) 
        smiles = get_smiles_pubchem(iupac)
        if smiles: return smiles, "PubChem (IUPAC)"

    # 2단계: IUPAC으로 실패했거나 IUPAC이 없는 경우, Name(약어/이름)으로 탐색
    if name and name != "N/A" and name != "nan":
        smiles = get_smiles_cir(name)
        if smiles: return smiles, "CIR (Name)"
        
        time.sleep(0.5)
        smiles = get_smiles_pubchem(name)
        if smiles: return smiles, "PubChem (Name)"

    return None, "Not Found"


# ==========================================
# 3. 메인 실행 함수
# ==========================================
def run_smiles_pipeline(folder: Path, db_path: Path, input_csv_path=None, output_csv_path=None):
    print(f"🚀 [SMILES 추출] 분석 시작: {folder.name}")

    input_csv = Path(input_csv_path) if input_csv_path is not None else folder / "compound_inventory_standardized.csv"
    opsin_jar = PROJECT_ROOT / "tools" / "opsin-cli.jar"

    if not input_csv.exists():
        print(f"  ! 에러: 인벤토리 CSV 파일을 찾을 수 없습니다. ({input_csv.name})")
        return

    # 기존 LNPDB 딕셔너리 빌드
    lnpdb_ref = build_lnpdb_reference(db_path)

    df = pd.read_csv(input_csv)
    print(f"  - 총 {len(df)}개 화합물에 대해 다중 API 추적을 시작합니다...")

    smiles_list = []
    source_list = []

    # 💡 [핵심 수정] 루프 내에서 처리 후 리스트에 담기
    for index, row in df.iterrows():
        name = row.get('Name', 'Unknown')
        novelty = row.get('Novelty', 'Unknown')

        print(f"    🔍 추적 중 [{novelty}]: {name} ... ", end="", flush=True)

        smiles, source = resolve_smiles(row, opsin_jar, lnpdb_ref)

        if smiles:
            print(f"✅ 발견 ({source})")
        else:
            print("❌ 실패")

        smiles_list.append(smiles)
        source_list.append(source)

    # DataFrame에 결과 추가
    df['SMILES'] = smiles_list
    df['SMILES_Source'] = source_list

    out_path = Path(output_csv_path) if output_csv_path is not None else folder / "compound_inventory_with_smiles.csv"
    df.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"\n  ✨ 최종 저장 완료: {out_path.name}")
    print(df[['Novelty', 'Name', 'SMILES', 'SMILES_Source']].head(10))

# ==========================================
# 실행부
# ==========================================
if __name__ == "__main__":
    TEST_FOLDER = Path(r"/Users/kogeon/Library/CloudStorage/GoogleDrive-geon@molcube.com/내 드라이브/EXTRACT-TEST/BEND-Excel-test")
    # 💡 LNPDB 원본 파일 경로를 지정해주세요.
    EXISTING_LNPDB_PATH = Path(r"/Users/kogeon/Google Drive/내 드라이브/LNPDB (1).csv") 

    try:
        import requests 
        if TEST_FOLDER.exists():
            run_smiles_pipeline(TEST_FOLDER, EXISTING_LNPDB_PATH)
        else:
            print(f"❌ 폴더 경로를 찾을 수 없습니다: {TEST_FOLDER}")
    except ImportError:
        print("❌ 'requests' 모듈이 필요합니다. 터미널에서 'pip install requests'를 실행해주세요.")
    except Exception as e:
        print(f"❌ 실행 중 오류 발생: {e}")
