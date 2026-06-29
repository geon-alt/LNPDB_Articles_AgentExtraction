import subprocess
from pathlib import Path


def pdf_to_md_marker(pdf_path, output_dir):
    """
    Marker 명령어를 사용하여 PDF를 Markdown으로 변환합니다.
    output_dir 아래에 [파일명]/[파일명].md 형태로 저장됩니다.
    """
    pdf_file = Path(pdf_path)
    output_dir = Path(output_dir)
    print(f"\n🚀 변환 시작: {pdf_file}")

    command = [
        "marker_single",
        str(pdf_file),
        "--output_dir",
        str(output_dir)
    ]

    try: 
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True
        ) # marker 실행 명령 실행

        expected_md_path = output_dir / pdf_file.stem / f"{pdf_file.stem}.md"

        if expected_md_path.exists():
            print(f"  ✨ [성공] 저장 완료: {expected_md_path}")
            return expected_md_path
        else:
            print("  ⚠️ Markdown 파일 경로를 예상했지만 생성되지 않았습니다.")
            if result.stdout:
                print("  stdout:", result.stdout[:1000])
            if result.stderr:
                print("  stderr:", result.stderr[:1000])
            return None

    except subprocess.CalledProcessError as e:
        print(f"  ❌ [실패] {pdf_file.name}")
        print(f"  에러 내용:\n{e.stderr}")
        return None
    except Exception as e:
        print(f"  ❌ [예외 발생] {pdf_file.name}")
        print(f"  상세 내용: {e}")
        return None


def find_all_pdfs(root_folder):
    """
    root_folder 아래의 모든 하위 폴더를 포함하여 PDF 파일을 찾습니다.
    """
    root = Path(root_folder)
    pdf_files = [
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() == ".pdf"
    ]
    return sorted(pdf_files)


def process_all_pdfs(root_folder):
    """
    상위 폴더 아래 모든 PDF를 찾아,
    각 PDF가 들어 있는 '원래 폴더'에 결과를 저장합니다.
    """
    root = Path(root_folder)
    if not root.exists():
        print(f"❌ 폴더가 존재하지 않습니다: {root}")
        return

    pdf_list = find_all_pdfs(root)
    if not pdf_list:
        print(f"📍 상위 폴더 아래에 PDF 파일이 없습니다: {root}")
        return

    print(f"📂 상위 폴더: {root}")
    print(f"📑 총 {len(pdf_list)}개의 PDF를 처리합니다.")
    print("=" * 80)

    success_count = 0
    fail_count = 0

    for i, pdf_path in enumerate(pdf_list, 1):
        rel_path = pdf_path.relative_to(root)
        print(f"[{i}/{len(pdf_list)}] {rel_path}")

        # 결과는 해당 PDF가 있는 폴더에 저장
        output_dir = pdf_path.parent
        md_path = pdf_to_md_marker(pdf_path, output_dir)

        if md_path is not None:
            success_count += 1
        else:
            fail_count += 1

    print("\n" + "=" * 80)
    print("✅ 모든 PDF 변환 작업이 종료되었습니다.")
    print(f"성공: {success_count}개")
    print(f"실패: {fail_count}개")


if __name__ == "__main__":
    # 상위 폴더만 지정하면 하위 폴더들까지 전부 탐색
    root_folder = Path(r"/Users/kogeon/python_projects_path/LNPDB_Articles_Extraction/Extraction_Examples/excel_o")
    process_all_pdfs(root_folder)