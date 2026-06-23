import cv2
import json
import sys
import os
from pathlib import Path
from PIL import Image

# =========================
# 1. Gemini (Vertex AI) API 설정 (제공해주신 로직 그대로 적용)
# =========================
CURRENT_DIR = Path(__file__).resolve().parent

PROJECT_ROOT = None
for p in [CURRENT_DIR, *CURRENT_DIR.parents]:
    if (p / "find_api.py").exists():
        PROJECT_ROOT = p
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
        break

API_IMPORT_ERROR = None
API_AVAILABLE = False

try:
    from find_api import find_api_key_file, get_vertexai_client
    # from google.genai import types # 필요 시 활성화
    API_AVAILABLE = True
except Exception as e:
    API_AVAILABLE = False
    API_IMPORT_ERROR = str(e)


# =========================
# 2. 자율 Y좌표 탐색 에이전트 루프
# =========================
def autonomous_y_finder(image_path, target_x, initial_y, client, max_iterations=7):
    """
    AI가 스스로 선을 이동시키며 정확한 Y 좌표를 찾는 루프 함수
    """
    image_cv = cv2.imread(image_path)
    if image_cv is None:
        print(f"❌ 오류: '{image_path}' 이미지를 찾을 수 없습니다.")
        return None

    current_y = initial_y
    print(f"\n🚀 [자동 추출 시작] Target X: {target_x}, Initial Y: {initial_y}")

    for i in range(max_iterations):
        test_img = image_cv.copy()
        
        # 가로선 긋기 (좌우 30픽셀, 두께 2픽셀, 빨간색)
        cv2.line(test_img, (target_x - 30, current_y), (target_x + 30, current_y), (0, 0, 255), 2)
        
        # 디버깅용 이미지 저장
        debug_filename = f"debug_step_{i+1}.jpg"
        cv2.imwrite(debug_filename, test_img)
        
        # PIL 이미지로 변환
        image_pil = Image.fromarray(cv2.cvtColor(test_img, cv2.COLOR_BGR2RGB))
        
        # 프롬프트 작성 (JSON 형식 강제)
        prompt = """
        Analyze this chart and return ONLY valid JSON.
        당신은 정밀한 데이터 추출 에이전트입니다. 
        이미지에 그려진 '빨간색 가로선'이 막대(또는 데이터 포인트)의 최상단 모서리에 완벽하게 일치하는지 평가하세요.
        이미지의 좌표계는 맨 위가 0이고, 아래로 갈수록 값이 커집니다.
        
        Required format:
        {
          "status": "PERFECT" or "ADJUST",
          "move_pixels": int
        }
        
        - 일치하면: {"status": "PERFECT", "move_pixels": 0}
        - 선이 데이터보다 낮아서 '위로' 올려야 하면 (예: 5픽셀 위로): {"status": "ADJUST", "move_pixels": -5}
        - 선이 데이터보다 높아서 '아래로' 내려야 하면 (예: 3픽셀 아래로): {"status": "ADJUST", "move_pixels": 3}
        
        Do not include markdown fences.
        """

        print(f"⏳ [{i+1}회차] AI 평가 대기 중... (현재 Y: {current_y})")
        try:
            # Vertex AI Gemini 호출 (제공해주신 코드 방식)
            res = client.models.generate_content(
                model="gemini-3.1-pro-preview",
                contents=[prompt, image_pil]
            )

            # Markdown 백틱 제거 및 JSON 파싱 (제공해주신 코드 방식)
            text = res.text.strip().replace("```json", "").replace("```", "").strip()
            result = json.loads(text)
            
            status = result.get("status", "ADJUST")
            move_pixels = result.get("move_pixels", 0)

            print(f"   ↳ AI 응답: 상태='{status}', 이동 제안={move_pixels}px")

            if status == "PERFECT" or move_pixels == 0:
                print(f"✅ [추출 완료] 완벽한 Y 좌표를 찾았습니다: {current_y}")
                break
            else:
                current_y += move_pixels
                current_y = max(0, min(current_y, image_cv.shape[0] - 1)) # 이미지 밖으로 나가지 않게 방어

        except Exception as e:
            print(f"❌ API 호출 또는 JSON 파싱 중 오류 발생: {e}")
            # 에러 발생 시 현재 응답 텍스트를 출력하여 원인 파악
            if 'res' in locals():
                print(f"   ↳ 원본 응답 텍스트: {res.text}")
            break

    return current_y

# =========================
# 3. 실행부
# =========================
if __name__ == "__main__":
    if not API_AVAILABLE:
        print(f"❌ Gemini API 모듈 import 실패: {API_IMPORT_ERROR}")
        sys.exit(1)

    try:
        # 본인의 프로젝트 환경에 맞게 key_path가 자동으로 설정됩니다.
        # 주의: 다른 사람의 키 파일 이름이 적혀있다면 본인 것으로 수정하세요.
        key_path = find_api_key_file("vertex-490605-8d0be916872a.json")
        client = get_vertexai_client(key_path)
        print("✅ Vertex AI Client 초기화 성공")
        
    except Exception as e:
        print(f"❌ Client 초기화 실패: {e}")
        sys.exit(1)

    # 테스트할 이미지와 초기 좌표 설정
    test_image = "/Users/kogeon/python_projects_path/LNPDB_Articles_Extraction/4_Extract_Exp_Vals/Exp_Vals_From_Figs/Example_Figs/fig2d.png" # 실제 테스트할 이미지 경로로 변경하세요.
    target_x_coord = 250             # X축 막대의 중앙 픽셀 위치
    initial_y_guess = 300            # 임의로 던져주는 시작 Y 픽셀 위치

    if os.path.exists(test_image):
        final_y = autonomous_y_finder(
            image_path=test_image, 
            target_x=target_x_coord, 
            initial_y=initial_y_guess, 
            client=client
        )
        print(f"\n🎯 최종 확정된 Y 픽셀 값: {final_y}")
    else:
        print(f"❌ 이미지 파일 '{test_image}'를 찾을 수 없습니다.")