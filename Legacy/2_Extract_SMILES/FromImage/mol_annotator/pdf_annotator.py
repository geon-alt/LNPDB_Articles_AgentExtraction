"""
PDF에 SMILES 팝업 주석 삽입
"""
import fitz
from typing import List, Tuple


def bbox_png_to_pdf(
    bbox_png: Tuple[int, int, int, int],
    img_width: int,
    img_height: int,
    page: fitz.Page,
) -> fitz.Rect:
    """
    PNG 픽셀 좌표 bbox를 PDF 좌표계로 변환

    Args:
        bbox_png: (y0, x0, y1, x1) in pixels
        img_width: PNG 이미지 너비 (pixels)
        img_height: PNG 이미지 높이 (pixels)
        page: fitz.Page 객체

    Returns:
        fitz.Rect: PDF 좌표계 rect
    """
    y0, x0, y1, x1 = bbox_png
    page_rect = page.rect  # PDF 페이지 크기 (points)

    # 픽셀 → PDF point 비율
    x_ratio = page_rect.width / img_width
    y_ratio = page_rect.height / img_height

    pdf_x0 = x0 * x_ratio
    pdf_y0 = y0 * y_ratio
    pdf_x1 = x1 * x_ratio
    pdf_y1 = y1 * y_ratio

    return fitz.Rect(pdf_x0, pdf_y0, pdf_x1, pdf_y1)


def annotate_pdf_page(
    pdf_path: str,
    output_path: str,
    page_num: int,
    bboxes: List[Tuple[int, int, int, int]],
    smiles_list: List[str],
    img_width: int,
    img_height: int,
) -> None:
    """
    PDF 페이지의 구조 위치에 SMILES 팝업 주석 삽입

    Args:
        pdf_path: 원본 PDF 경로
        output_path: 출력 PDF 경로
        page_num: 페이지 번호 (1-indexed)
        bboxes: [(y0, x0, y1, x1), ...] in PNG 픽셀 좌표
        smiles_list: SMILES 문자열 리스트
        img_width: PNG 이미지 너비
        img_height: PNG 이미지 높이
    """
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]

    for i, (bbox, smiles) in enumerate(zip(bboxes, smiles_list)):
        if not smiles:
            continue

        pdf_rect = bbox_png_to_pdf(bbox, img_width, img_height, page)

        # 구조 위에 하이라이트
        highlight = page.add_highlight_annot(pdf_rect)
        highlight.set_colors(stroke=[0.2, 0.6, 1.0])  # 파란색
        highlight.update()

        # 클릭 시 SMILES 팝업
        annot = page.add_text_annot(
            pdf_rect.top_left,
            f"Structure {i+1}\nSMILES: {smiles}",
            icon="Note",
        )
        annot.set_info(title=f"Structure {i+1}", content=f"SMILES:\n{smiles}")
        annot.update()

    doc.save(output_path)
    doc.close()
    print(f"주석 PDF 저장: {output_path}")