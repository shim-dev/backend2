# routes/post.py
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta, timezone
from extensions import mongo
import google.generativeai as genai
import os, json, re, ast, time, logging
from typing import List, Dict, Any

post_bp = Blueprint("post", __name__, url_prefix="/posts")

ALLOWED_DIFFICULTY = {"상", "중", "하"}

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
TEXT_MODEL = genai.GenerativeModel("gemini-2.5-flash")

def _now():
    return datetime.utcnow()

# ---------- LLM 헬퍼 함수 ----------
def _gen_call(model, contents, *, json_only=False, timeout=15, retries=3, backoff_base=0.6):
    """
    Gemini generate_content 안전 호출:
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
            time.sleep(backoff_base * (2 ** i))
    logging.exception("Gemini call failed after retries: %s", last_err)
    return None

def _extract_text_safe(resp):
    """candidates/parts가 비어도 터지지 않도록 안전하게 텍스트 추출."""
    if not resp or not getattr(resp, "candidates", None):
        return None
    cand = resp.candidates[0]
    
    # ✅ pieces 리스트를 항상 먼저 초기화합니다.
    pieces = []
    
    if getattr(cand, "content", None) and getattr(cand.content, "parts", None):
        for p in cand.content.parts:
            if hasattr(p, "text") and p.text is not None:
                pieces.append(p.text)
    
    return "".join(pieces).strip() if pieces else None

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
- 올리브오일
- 와인

제한군: 뇌 건강에 해로운 음식군 (낮은 점수)
- 붉은 고기: 소고기, 돼지고기, 양고기
- 버터/마가린
- 치즈
- 과자/디저트: 케이크, 쿠키, 아이스크림
- 튀김/패스트푸드: 감자튀김, 햄버거
"""

def get_slow_aging_score(ingredients: list, steps: list) -> Dict[str, Any]:
    """
    LLM을 사용하여 레시피의 저속노화 점수를 생성
    """
    ingredients_str = ", ".join(ingredients) if ingredients else "없음"
    steps_str = "\n".join(steps) if steps else "없음"

    prompt = f"""
너는 '저속노화'에 대해 잘 아는 전문 영양 코치야.
다음 레시피의 재료와 조리법을 분석해서 '저속노화' 점수를 100점 만점으로 매겨줘.
점수 기준은 아래의 'MIND 식단 점수 규칙'을 따르며, 100점에 가까울수록 가공되지 않은 신선한 재료와 건강한 조리법을 사용한 거야.
1점에 가까울수록 튀김, 설탕, 가공식품 등 저속노화에 좋지 않은 요소가 많아.

# MIND 식단 점수 규칙
{mind_rules}

아래 항목들을 JSON 형식으로 응답해줘.
- 'score': 1~100점 사이의 정수 점수
- 'notes': 점수에 대한 간단한 분석과 설명 (예: "튀김이 많아 점수가 낮습니다.")
- 'recommendation': 레시피를 저속노화 관점에서 더 좋게 만드는 구체적인 팁 (예: "튀기는 대신 굽거나 쪄서 조리해보세요.")

응답 형식:
{{
  "score": (점수),
  "notes": "(분석)",
  "recommendation": "(추천)"
}}

---
레시피 정보
재료: {ingredients_str}
조리 순서: {steps_str}
"""
    resp = _gen_call(TEXT_MODEL, prompt, json_only=True)
    text = _extract_text_safe(resp)
    
    if text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logging.error("Failed to parse LLM response: %s", text)
            pass
    return {"score": 0, "notes": "분석 실패", "recommendation": "레시피 분석에 실패했습니다."}

# ---------- 유효성 검사 및 라우트 ----------
def _validate_recipe(data: dict) -> Dict[str, str]:
    errors = {}
    # name (레시피 이름)
    name = (data.get("name") or "").strip()
    if not (1 <= len(name) <= 100):
        errors["name"] = "1~100자 필수"
    # desc (설명)
    desc = (data.get("desc") or "").strip()
    if not (1 <= len(desc) <= 5000):
        errors["desc"] = "1~5000자 필수"
    # keywords (키워드)
    keywords = data.get("keywords", [])
    if keywords:
        if not isinstance(keywords, list):
            errors["keywords"] = "문자열 배열이어야 함"
        elif len(keywords) > 10 or any(not isinstance(c, str) or not c.strip() for c in keywords):
            errors["keywords"] = "빈 값 불가, 최대 10개"
        # time (소요 시간)
    time_val = data.get("time") # 변수 이름 변경
    if time_val is not None:
        if not isinstance(time_val, (int, str)):
            errors["time"] = "정수 또는 문자열 형식의 숫자"
        else:
            try:
                if not (1 <= int(time_val) <= 1440):
                    errors["time"] = "1~1440 범위의 정수"
            except ValueError:
                errors["time"] = "숫자로 변환할 수 없는 값"
    else:
        errors["time"] = "소요 시간 필수"
    # level (난이도)
    level = data.get("level")
    if level is not None:
        # ✅ 유효성 검사에서 한글 난이도 값을 사용
        if not isinstance(level, str) or level not in ALLOWED_DIFFICULTY:
            errors["level"] = "상/중/하 중 하나"
    # imageUrl (단일 이미지 URL)
    imageUrl = data.get("imageUrl", "") # ✅ data.get() 사용
    if imageUrl: # ✅ imageUrl 변수 사용
        if not isinstance(imageUrl, str) or not imageUrl.startswith("http"):
            errors["imageUrl"] = "올바른 URL 형식이어야 합니다."
    # serving
    serving = data.get("serving")
    if serving is not None:
        if not isinstance(serving, int) or not (1 <= serving <= 100):
            errors["serving"] = "1~100 범위의 정수"
    # ingredients
    ingredients = data.get("ingredients", [])
    if not isinstance(ingredients, list) or not ingredients:
        errors["ingredients"] = "최소 1개 이상의 재료가 필요합니다."
    # steps
    steps = data.get("steps", [])
    if not isinstance(steps, list) or not steps:
        errors["steps"] = "최소 1개 이상의 조리 순서가 필요합니다."
    
    return errors

@post_bp.route("/recipe", methods=["POST"])
def create_recipe():
    try:
        data = request.get_json(silent=True) or {}
        
        required_fields = ["name", "desc", "time", "level", "serving", "ingredients", "steps"]
        if not all(k in data for k in required_fields):
            return jsonify({"ok": False, "error": "missing_fields", "message": "필수 필드가 누락되었습니다."}), 400

        errors = _validate_recipe(data)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400

        llm_score_result = get_slow_aging_score(
            ingredients=data.get("ingredients", []),
            steps=data.get("steps", [])
        )
        
        time_int = int(data.get("time", 0))

        doc = {
            "name": data.get("name", "").strip(),
            "keywords": data.get("keywords", []),
            "desc": data.get("desc", "").strip(),
            "time": time_int,
            "level": data.get("level", ""),
            "imageUrl": data.get("imageUrl", ""),
            "serving": data.get("serving"),
            "steps": data.get("steps", []),
            "ingredients": data.get("ingredients", []),
            "score": llm_score_result.get("score", 0),
            "notes": llm_score_result.get("notes", ""),
            "recommendation": llm_score_result.get("recommendation", ""),
            "views": data.get("views", 0),
            "created_at": _now(),
        }

        res = mongo.db.recipes.insert_one(doc)
        doc["_id"] = str(res.inserted_id)
        return jsonify({"ok": True, "recipe": doc}), 201

    except Exception as e:
        import traceback, logging
        logging.error("create_recipe fatal: %s\n%s", e, traceback.format_exc())
        return jsonify({"ok": False, "error": "internal_error", "message": str(e)}), 500