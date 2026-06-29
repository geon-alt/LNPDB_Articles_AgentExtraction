import os
import sys
import numpy as np
import pandas as pd
from PIL import Image
import fitz
from pathlib import Path
import time

# --- [경로 설정] ---
# 현재 위치: 2_Extract_SMILES/FromImage/mol_annotator/
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 동일 폴더 내 모듈 임포트
try:
    from segmentation import segment_with_bboxes
    from recognition import load_molscribe, predict_smiles_batch
    from pdf_annotator import annotate_pdf_page
except ImportError as e:
    print(f"⚠️ 모듈 로드 실패: {e}. 모든 .py 파일이 동일 폴더에 있는지 확인하세요.")

def run_pipeline_for_pdf(
    pdf_path: Path,
    output_root: Path,
    device: str = 'cpu',
    dpi: int = 300,
):
    """단일 PDF의 모든 페이지를 처리하여 전용 폴더에 저장하고 주석 PDF를 생성합니다."""
    # 💡 폴더명 규칙: PDF명_structure
    pdf_output_dir = output_root / f"{pdf_path.stem}_structure"
    pdf_output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n📄 [PDF 분석 시작] {pdf_path.name}")
    print(f"📁 [저장 경로] {pdf_output_dir}")

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    
    # MolScribe 모델 로드
    from recognition import load_molscribe
    model = load_molscribe(device=device)

    all_page_results = []
    
    # 💡 최종 주석 PDF 생성을 위한 복사본 생성 (원본 유지)
    annotated_doc = fitz.open(str(pdf_path))

    for page_num in range(1, total_pages + 1):
        print(f"  [Page {page_num}/{total_pages}] 처리 중...", end=" ", flush=True)
        
        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=dpi)
        img_path = pdf_output_dir / f"page_{page_num:04d}.png"
        pix.save(str(img_path))
        img_width, img_height = pix.width, pix.height

        # 세그멘테이션 (오류 방지를 위한 예외 처리 추가)
        try:
            image = np.array(Image.open(img_path))
            segments, bboxes = segment_with_bboxes(image, expand=True)
        except Exception as e:
            print(f"❌ 세그멘테이션 에러: {e}")
            continue

        if len(segments) == 0:
            print("건너뜀 (구조 없음)")
            continue

        # 세그먼트 이미지 저장
        seg_dir = pdf_output_dir / f"page_{page_num:04d}_segments"
        seg_dir.mkdir(parents=True, exist_ok=True)
        for i, seg in enumerate(segments):
            seg_path = seg_dir / f"struct_{i+1:03d}.png"
            Image.fromarray(seg).save(str(seg_path))

        # SMILES 변환
        smiles_list = predict_smiles_batch(model, segments)

        # 결과 데이터 수집
        page_df = pd.DataFrame({
            "page": [page_num] * len(smiles_list),
            "structure_id": [i+1 for i in range(len(smiles_list))],
            "smiles": smiles_list,
            "bbox_y0": [b[0] for b in bboxes],
            "bbox_x0": [b[1] for b in bboxes],
            "bbox_y1": [b[2] for b in bboxes],
            "bbox_x1": [b[3] for b in bboxes]
        })
        all_page_results.append(page_df)

        # 💡 [핵심] 개별 페이지가 아닌 전체 문서 객체(annotated_doc)에 주석 추가
        # pdf_annotator.py의 로직을 활용하여 Note 아이콘 삽입
        from pdf_annotator import bbox_png_to_pdf
        annot_page = annotated_doc[page_num - 1]
        
        for i, (bbox, smiles) in enumerate(zip(bboxes, smiles_list)):
            if not smiles: continue
            
            pdf_rect = bbox_png_to_pdf(bbox, img_width, img_height, annot_page)
            
            # 하이라이트 추가
            highlight = annot_page.add_highlight_annot(pdf_rect)
            highlight.set_colors(stroke=[0.2, 0.6, 1.0])
            highlight.update()

            # 💡 SMILES 팝업 노트(Note) 추가
            annot = annot_page.add_text_annot(
                pdf_rect.top_left,
                f"Structure {i+1}\nSMILES: {smiles}",
                icon="Note",
            )
            annot.set_info(title=f"Structure {i+1}", content=f"SMILES:\n{smiles}")
            annot.update()
            
        print("✅")

    # 💡 최종 결과 저장
    if all_page_results:
        # 1. 통합 CSV 저장
        final_df = pd.concat(all_page_results, ignore_index=True)
        csv_path = pdf_output_dir / f"{pdf_path.stem}_all_results.csv"
        final_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        
        # 2. 💡 주석이 포함된 전체 PDF 저장
        final_pdf_path = pdf_output_dir / f"{pdf_path.stem}_annotated.pdf"
        annotated_doc.save(str(final_pdf_path))
        
        print(f"\n✨ {pdf_path.name} 완료!")
        print(f"   - 전체 결과 CSV: {csv_path.name}")
        print(f"   - 주석 포함 PDF: {final_pdf_path.name}")
    else:
        print(f"\n⚠️ {pdf_path.name}에서 추출된 구조가 없습니다.")

    doc.close()
    annotated_doc.close()
    
def batch_process_folder(input_folder_path: str, output_root_path: str):
    """폴더 내의 모든 PDF를 찾아 순차적으로 처리합니다."""
    input_folder = Path(input_folder_path)
    output_root = Path(output_root_path)
    
    # 💡 폴더 내 모든 PDF 파일 탐색 (임시파일 제외)
    pdf_files = sorted([f for f in input_folder.glob("*.pdf") if not f.name.startswith("~")])
    
    if not pdf_files:
        print(f"❌ '{input_folder}' 폴더 내에 PDF 파일이 없습니다.")
        return

    print(f"🚀 총 {len(pdf_files)}개의 PDF 파일을 발견했습니다. 일괄 처리를 시작합니다.")
    start_time = time.time()

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{len(pdf_files)}] 작업 대상: {pdf_path.name}")
        try:
            run_pipeline_for_pdf(pdf_path, output_root, device='cpu')
        except Exception as e:
            print(f"❌ {pdf_path.name} 처리 중 에러 발생: {e}")

    total_elapsed = time.time() - start_time
    print(f"\n{'='*60}\n✨ 모든 PDF 처리 완료! (총 소요 시간: {int(total_elapsed // 60)}분 {int(total_elapsed % 60)}초)")

if __name__ == "__main__":
    # kogeon님의 실제 경로에 맞춰 수정
    # 💡 PDF들이 들어있는 원본 폴더
    INPUT_PDF_DIR = r"G:\내 드라이브\EXTRACT-TEST\BEND-Excel-test"
    
    # 💡 결과 폴더들이 생성될 루트 경로
    RESULT_ROOT_DIR = r"G:\내 드라이브\EXTRACT-TEST\BEND-Excel-test"

    batch_process_folder(INPUT_PDF_DIR, RESULT_ROOT_DIR)