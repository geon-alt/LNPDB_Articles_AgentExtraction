from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def pdf_to_md_marker(pdf_path: str | Path, output_dir: str | Path) -> Path | None:
    """Run marker_single for one PDF and return the expected markdown path."""
    pdf_file = Path(pdf_path)
    output_dir = Path(output_dir)
    command = ["marker_single", str(pdf_file), "--output_dir", str(output_dir)]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"[marker failed] {pdf_file}: {exc.stderr}")
        return None
    except Exception as exc:
        print(f"[marker error] {pdf_file}: {exc}")
        return None

    expected_md_path = output_dir / pdf_file.stem / f"{pdf_file.stem}.md"
    if expected_md_path.exists():
        return expected_md_path
    if result.stdout:
        print(f"[marker stdout] {result.stdout[:1000]}")
    if result.stderr:
        print(f"[marker stderr] {result.stderr[:1000]}")
    return None


def find_all_pdfs(root_folder: str | Path) -> list[Path]:
    """Find all PDFs under a root folder."""
    root = Path(root_folder)
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")


def process_all_pdfs(root_folder: str | Path) -> dict[str, int]:
    """Convert all PDFs under a root folder, writing each result beside the source PDF."""
    root = Path(root_folder)
    if not root.exists():
        raise FileNotFoundError(root)
    success_count = 0
    fail_count = 0
    pdf_files = find_all_pdfs(root)
    for index, pdf_path in enumerate(pdf_files, 1):
        print(f"[{index}/{len(pdf_files)}] {pdf_path.relative_to(root)}")
        if pdf_to_md_marker(pdf_path, pdf_path.parent) is None:
            fail_count += 1
        else:
            success_count += 1
    return {"pdfs": len(pdf_files), "success": success_count, "failed": fail_count}


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert PDFs under a folder using marker_single.")
    parser.add_argument("--root", required=True, help="Paper folder or parent folder to scan recursively.")
    args = parser.parse_args()
    print(process_all_pdfs(args.root))


if __name__ == "__main__":
    main()

