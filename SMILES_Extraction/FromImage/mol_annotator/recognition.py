"""
MolScribe 래퍼
"""
import os
import numpy as np
from PIL import Image
from typing import List
import huggingface_hub
from molscribe import MolScribe


def load_molscribe(device: str = 'cuda') -> MolScribe:
    """
    MolScribe 모델 로드

    Args:
        device: 'cuda' or 'cpu'

    Returns:
        MolScribe 모델
    """
    model_path = huggingface_hub.hf_hub_download(
        repo_id='yujieq/MolScribe',
        filename='swin_base_char_aux_1m680k.pth'
    )
    model = MolScribe(model_path, device=device)
    return model


def predict_smiles_batch(
    model: MolScribe,
    segments: List[np.array],
) -> List[str]:
    smiles_list = []
    for i, seg in enumerate(segments):
        try:
            # RGBA → RGB 변환 후 numpy array로 유지
            img = Image.fromarray(seg)
            if img.mode == 'RGBA':
                bg = Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # numpy array로 변환해서 넘기기
            img_array = np.array(img)
            result = model.predict_image(img_array, return_atoms_bonds=False)
            smiles = result.get('smiles', '') if isinstance(result, dict) else str(result)
            smiles_list.append(smiles)
            print(f"  [{i+1}/{len(segments)}] SMILES: {smiles}")
        except Exception as e:
            print(f"  [{i+1}/{len(segments)}] 변환 실패: {e}")
            smiles_list.append('')
    return smiles_list