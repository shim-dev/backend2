# routes/chat/chat_meal.py
from flask import Blueprint, request, jsonify
from extensions import mongo
from datetime import datetime
from dotenv import load_dotenv
import os, json, re, ast, base64, requests
import google.generativeai as genai
import time
import logging

chat_meal_bp = Blueprint('chat_meal', __name__)

# --- Gemini 설정 ---
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
TEXT_MODEL = genai.GenerativeModel("gemini-2.5-flash")
VISION_MODEL = genai.GenerativeModel("gemini-2.5-flash")

# MIND 카테고리 (화이트리스트)
MIND_CATEGORIES = {
    "green_leafy_veg": "녹색 잎채소",
    "other_veg": "기타 채소",
    "nuts": "견과류",
    "berries": "베리류",
    "beans": "콩/두류",
    "whole_grains": "통곡물",
    "fish": "생선",
    "poultry": "가금류",
    "olive_oil": "올리브유",
    "wine": "와인",
    "red_meats": "붉은 고기",
    "butter_margarine": "버터/마가린",
    "cheese": "치즈",
    "pastries_sweets": "과자/디저트",
    "fried_fast_food": "튀김/패스트푸드"
}

# ---------- 공통 헬퍼 ----------
def _extract_text_safe(resp):
    """candidates/parts가 비어도 터지지 않도록 안전하게 텍스트 추출."""
    if not resp or not getattr(resp, "candidates", None):
        return None
    cand = resp.candidates[0]
    if not getattr(cand, "content", None) or not getattr(cand.content, "parts", None):
        return None
    pieces = []
    for p in cand.content.parts:
        if hasattr(p, "text") and p.text is not None:
            pieces.append(p.text)
    return "".join(pieces).strip() if pieces else None

def safe_parse_foods(text: str):
    """모델이 JSON 외 텍스트/코드블록을 섞어 보낼 때도 최대한 리스트를 복구."""
    if not text:
        return []
    cleaned = re.sub(r"```(?:json)?", "", text).strip("` \n\t")
    # dict 또는 list 파싱 시도
    for parser in (json.loads, ast.literal_eval):
        try:
            obj = parser(cleaned)
            if isinstance(obj, dict) and isinstance(obj.get("foods"), list):
                return obj["foods"]
            if isinstance(obj, list):
                return obj
        except Exception:
            pass
    # 텍스트 중 첫 배열 추출
    m = re.search(r"\[.*?\]", cleaned, re.S)
    if m:
        frag = m.group(0)
        for parser in (json.loads, ast.literal_eval):
            try:
                arr = parser(frag)
                if isinstance(arr, list):
                    return arr
            except Exception:
                pass
    return []

def _gen_call(model, contents, *, json_only=False, timeout=15, retries=3, backoff_base=0.6):
    """
    Gemini generate_content 안전 호출:
    - timeout: 초 단위(요청 옵션)
    - retries: 지수 백오프 재시도
    - json_only=True면 application/json 강제
    실패 시 None 반환
    """
    genconf = {"response_mime_type": "application/json"} if json_only else None
    last_err = None
    for i in range(retries):
        try:
            resp = model.generate_content(
                contents,
                generation_config=genconf,
                request_options={"timeout": timeout}
            )
            return resp
        except Exception as e:
            last_err = e
            # 429/500 등은 살짝 쉬었다가 재시도
            time.sleep(backoff_base * (2 ** i))
    logging.exception("Gemini call failed after retries: %s", last_err)
    return None

# ---------- 음식 추출 ----------
def extract_food_names(message: str):
    if not message or not message.strip():
        return []

    prompt = f"""
다음 문장에서 음식 이름만 리스트로 뽑아줘.
다른 설명 없이 반드시 ["음식1","음식2"] 형태의 JSON 배열로만 응답해.
문장: "{message}"
"""
    # 1차: JSON 강제 + 재시도
    resp = _gen_call(TEXT_MODEL, prompt, json_only=True, timeout=12, retries=3)
    text = _extract_text_safe(resp) if resp else None
    if text:
        try:
            foods = json.loads(text)
            if isinstance(foods, list):
                return foods
        except Exception:
            pass

    # 2차: 일반 텍스트 모드 + 재시도 → 백업 파서
    resp2 = _gen_call(TEXT_MODEL, prompt, json_only=False, timeout=12, retries=2)
    text2 = _extract_text_safe(resp2) if resp2 else None
    if text2:
        foods = safe_parse_foods(text2)
        if foods:
            return foods

    return []

def extract_foods_from_image_bytes(image_bytes: bytes, mime: str = "image/jpeg"):
    if not image_bytes:
        return []

    prompt = '이미지에 보이는 음식 이름만 추출해서 ["음식1","음식2"] 형태의 JSON 배열로만 응답.'

    # 1차: JSON 강제
    resp = _gen_call(
        VISION_MODEL,
        [{"text": prompt}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(image_bytes).decode("utf-8")}}],
        json_only=True, timeout=15, retries=3
    )
    text = _extract_text_safe(resp) if resp else None
    if text:
        try:
            foods = json.loads(text)
            if isinstance(foods, list):
                return foods
        except Exception:
            pass

    # 2차: 일반 텍스트 → 백업 파서
    resp2 = _gen_call(
        VISION_MODEL,
        [{"text": prompt}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(image_bytes).decode("utf-8")}}],
        json_only=False, timeout=15, retries=2
    )
    text2 = _extract_text_safe(resp2) if resp2 else None
    if text2:
        foods = safe_parse_foods(text2)
        if foods:
            return foods

    return []

# ---------- MIND 점수 ----------
def score_foods_mind(foods: list, meal_type: str):
    if not foods:
        return {"items": [], "meal_score": 0.0, "notes": "음식 목록이 비어있습니다.", "recommendation": "식사를 기록해 보세요!"}

    mind_rules = """
건강군: 뇌 건강에 매우 좋은 음식군 (높은 점수)
- 녹색 잎채소: 케일, 시금치, 상추
- 기타 채소: 브로콜리, 당근, 토마토
- 견과류: 호두, 아몬드
- 베리류: 딸기, 블루베리
- 콩/두류: 렌즈콩, 두부
- 통곡물: 현미, 오트밀
- 생선: 연어, 고등어
- 가금류: 닭고기, 오리고기
- 올리브유
- 와인

제한군: 뇌 건강에 해로운 음식군 (낮은 점수)
- 붉은 고기: 소고기, 돼지고기, 양고기
- 버터/마가린
- 치즈
- 과자/디저트: 케이크, 쿠키, 아이스크림
- 튀김/패스트푸드: 감자튀김, 햄버거
"""

    prompt = f"""
너는 '저속노화'에 대해 잘 아는 영양 코치다. 다음 음식들을 MIND 식단 기준에 따라 100점 만점 점수를 매겨줘.
100점에 가까울수록 뇌 건강과 저속노화에 좋은 식단이야.
아래 규칙을 고려하여, 각 음식에 대한 점수(score), 카테고리, 간단한 설명을 JSON 객체로 반환해.

# MIND 식단 점수 규칙
{mind_rules}

- 각 음식에 대해 MIND 카테고리를 지정하고, 100점 만점 점수(score)를 정수로 산출해.
- 'note'에는 점수에 대한 간단한 설명을 남겨줘.
- 'recommendation'에는 다음 식사는 어떤 식으로 먹어보면 좋을지 저속노화 관점에서 구체적인 팁을 제공해줘.
- 'recommendation'와 'note'는 말풍선에 담기기 쉽게 간단하게 작성해줘.
- **입력된 음식 외에 함께 먹는 다른 음식은 평가에 포함하지 마.**
- 반드시 JSON 객체만 응답해.
  - 예시: {{"items":[ {{"food":"닭가슴살 샐러드", "categories":["가금류", "녹색 잎채소", "기타 채소"], "score":90, "note":"뇌 건강에 좋은 채소와 단백질이 풍부합니다."}}, {{"food":"족발", "categories":["붉은 고기"], "score":30, "note":"붉은 고기 위주로 구성되어 있어 점수가 낮습니다."}} ], "notes":"오늘 식단은 뇌 건강에 매우 긍정적입니다.", "recommendation": "다음 식사에는 붉은 고기 대신 생선이나 닭가슴살을 선택해 보세요. 더 많은 통곡물과 채소를 곁들이는 것도 좋습니다."}}

음식 리스트: {foods}
식사 타입: {meal_type}
"""

    resp = _gen_call(TEXT_MODEL, prompt, json_only=True, timeout=15, retries=3)
    text = _extract_text_safe(resp) if resp else None
    
    # 1. JSON 코드블록이 있거나 없거나 안정적으로 파싱
    data = {}
    if text:
        try:
            # 먼저 JSON 코드 블록을 제거하고 파싱 시도
            cleaned_text = re.sub(r"```(?:json)?|```", "", text, flags=re.DOTALL).strip()
            data = json.loads(cleaned_text)
        except json.JSONDecodeError:
            # 실패 시, 텍스트에서 가장 큰 JSON 객체 추출 시도
            try:
                match = re.search(r'\{.*\}', text, re.DOTALL)
                if match:
                    data = json.loads(match.group(0))
            except Exception as e:
                logging.error("Failed to parse JSON from Gemini response: %s | Error: %s", text, e)
    
    logging.info(f"Gemini raw response: {text}")
    logging.info(f"Parsed data: {data}")

    # 2. 파싱된 데이터에서 items 리스트 가져오기
    items = data.get("items", []) if isinstance(data, dict) else []
    notes = data.get("notes", "") if isinstance(data, dict) else ""
    recommendation = data.get("recommendation", "") # ✅ 이 부분을 추가했습니다
    
    meal_score_total = 0.0
    valid_item_count = 0
    
    for it in items:
        # 3. 점수 추출 및 유효성 검사
        score_val = it.get("score")
        if isinstance(score_val, (int, float)):
            score = max(0, min(100, int(score_val)))
            meal_score_total += score
            valid_item_count += 1
            it["score"] = score
        else:
            logging.warning(f"Invalid score value for food '{it.get('food')}': {score_val}")
            it["score"] = 0
            
        # MIND 카테고리만 허용
        it["categories"] = [c for c in it.get("categories", []) if c in MIND_CATEGORIES]
        
    denom = max(1, valid_item_count)
    final_meal_score = round(meal_score_total / denom, 1)

    logging.info(f"Calculated final meal score: {final_meal_score}")

    # ✅ 반환 값에 recommendation을 추가합니다
    return {"items": items, "meal_score": final_meal_score, "notes": notes, "recommendation": recommendation}

# ---------- 라우트 ----------
@chat_meal_bp.route('/chat-meal', methods=['POST'])
def chat_meal():
    try:
        data = request.get_json(force=True)
        nickname = data.get('nickname', 'test_user')
        message = data.get('message', '')
        meal_type = data.get('meal_type', '')
        image_url = data.get('image_url', '')

        if image_url:
            r = requests.get(image_url, timeout=10)
            r.raise_for_status()
            mime = (r.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
            foods = extract_foods_from_image_bytes(r.content, mime=mime)
            source = "image"
        else:
            foods = extract_food_names(message)
            source = "text"

        mind_result = score_foods_mind(foods, meal_type)

        mongo.db.diet_records.insert_one({
            "nickname": nickname,
            "meal_type": meal_type,
            "message": message,
            "image_url": image_url or None,
            "foods": foods,
            "mind": mind_result,
            "timestamp": datetime.now()
        })

        return jsonify({"success": True, "foods": foods, "mind": mind_result, "source": source})
    except Exception as e:
        import traceback, logging
        logging.error("chat-meal fatal: %s\n%s", e, traceback.format_exc())
        return jsonify({"success": False, "foods": [], "mind": {"items": [], "meal_score": 0.0, "notes": ""}, "source": "unknown"}), 200
