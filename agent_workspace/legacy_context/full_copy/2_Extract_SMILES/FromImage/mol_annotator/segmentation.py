"""
DECIMER-Seg 래퍼
bbox를 함께 반환하도록 수정
"""
import os
#os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

import numpy as np
from PIL import Image
from typing import List, Tuple
from decimer_segmentation.decimer_segmentation import (
    get_mrcnn_results,
    get_expanded_masks,
    apply_masks,
    sort_segments_bboxes,
)


def segment_with_bboxes(
    image: np.array,
    expand: bool = True,
) -> Tuple[List[np.array], List[Tuple[int, int, int, int]]]:
    """
    이미지에서 화학 구조를 세그멘테이션하고
    crop 이미지와 bbox를 함께 반환

    Args:
        image: 페이지 이미지 (np.array)
        expand: mask expansion 여부

    Returns:
        segments: crop된 구조 이미지 리스트
        bboxes: [(y0, x0, y1, x1), ...] in 픽셀 좌표
    """
    if expand:
        masks = get_expanded_masks(image)
    else:
        masks, _, _ = get_mrcnn_results(image)

    segments, bboxes = apply_masks(image, masks)

    if len(segments) == 0:
        return [], []

    segments, bboxes = sort_segments_bboxes(list(segments), list(bboxes))

    # 빈 세그먼트 필터링
    valid = [(seg, bb) for seg, bb in zip(segments, bboxes)
             if seg.shape[0] > 0 and seg.shape[1] > 0]

    if not valid:
        return [], []

    segments, bboxes = zip(*valid)
    return list(segments), list(bboxes)