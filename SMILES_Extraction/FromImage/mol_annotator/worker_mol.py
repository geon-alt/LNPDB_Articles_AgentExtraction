import sys
import json
import os
import numpy as np
from PIL import Image
import warnings
import traceback

# 💡 라이브러리 경고 및 로그 억제
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
warnings.filterwarnings('ignore')

try:
    from segmentation import segment_with_bboxes
    from recognition import load_molscribe, predict_smiles_batch
except ImportError as e:
    sys.stderr.write(f"ImportError: {str(e)}\n")
    sys.exit(1)


# 💡 [핵심 추가] 모든 Numpy 타입을 파이썬 표준 타입으로 강제 변환하는 인코더
class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NumpyEncoder, self).default(obj)


def main():
    if len(sys.argv) < 2: return
    temp_json_path = sys.argv[1]

    try:
        with open(temp_json_path, 'r', encoding='utf-8') as f:
            raw_items = json.load(f)

        img_items = []
        for item in raw_items:
            if isinstance(item, dict):
                img_items.append({
                    "path": item.get("path", ""),
                    "source_type": item.get("source_type", "pdf_page"),
                    "page_num": item.get("page_num"),
                })
            else:
                img_items.append({
                    "path": item,
                    "source_type": "pdf_page",
                    "page_num": None,
                })
    except Exception as e:
        sys.stderr.write(f"FileReadError: {str(e)}\n")
        return

    # 모델 로드
    try:
        model = load_molscribe(device='cpu')
    except Exception as e:
        sys.stderr.write(f"ModelLoadError: {str(e)}\n")
        sys.exit(1)

    all_results = []
    for item in img_items:
        path = item.get("path", "")
        source_type = item.get("source_type", "pdf_page")
        page_num = item.get("page_num")
        try:
            if not os.path.exists(path): continue

            image = np.array(Image.open(path))
            segments, bboxes = segment_with_bboxes(image, expand=True)

            if not segments:
                all_results.append({
                    "path": path,
                    "source_type": source_type,
                    "page_num": page_num,
                    "bboxes": [],
                    "smiles": []
                })
                continue

            # SMILES 예측
            smiles_list = []
            for seg in segments:
                try:
                    s = predict_smiles_batch(model, [seg])[0]
                    smiles_list.append(s)
                except Exception:
                    smiles_list.append("RECOGNITION_ERROR")

            # 결과 수집
            all_results.append({
                "path": path,
                "source_type": source_type,
                "page_num": page_num,
                "bboxes": bboxes,
                "smiles": smiles_list
            })

        except Exception as e:
            all_results.append({
                "path": path,
                "source_type": source_type,
                "page_num": page_num,
                "error": str(e)
            })

    # [핵심 수정] cls=NumpyEncoder를 사용하여 안전하게 JSON 변환
    json_data = json.dumps(all_results, cls=NumpyEncoder)
    sys.stdout.write(f"\nJSON_START{json_data}JSON_END\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()