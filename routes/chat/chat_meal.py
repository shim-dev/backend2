# routes/chat/chat_meal.py
from flask import Blueprint, request, jsonify
from extensions import mongo
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os, json, re, ast, base64, requests
import google.generativeai as genai
import time
import logging
from bson import ObjectId

# --- Blueprint 설정 ---
chat_meal_bp = Blueprint('chat_meal', __name__, url_prefix='/api')

# --- Gemini 설정 (GEMINI_API_KEY / 2.5-flash) ---
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
TEXT_MODEL   = genai.GenerativeModel("gemini-2.5-flash")
VISION_MODEL = genai.GenerativeModel("gemini-2.5-flash")

# --- MIND 카테고리 (화이트리스트)
#  - 모델이 한국어/영어 카테고리를 혼용해도 통과되도록 양쪽 키를 모두 허용
MIND_CATEGORIES = {
    # 건강군(긍정)
    "녹색 잎채소": "녹색 잎채소", "green_leafy_veg": "녹색 잎채소",
    "기타 채소": "기타 채소", "other_veg": "기타 채소",
    "견과류": "견과류", "nuts": "견과류",
    "베리류": "베리류", "berries": "베리류",
    "콩/두류": "콩/두류", "beans": "콩/두류", "legumes": "콩/두류",
    "통곡물": "통곡물", "whole_grains": "통곡물",
    "생선": "생선", "fish": "생선",
    "가금류": "가금류", "poultry": "가금류",
    "올리브유": "올리브유", "olive_oil": "올리브유",
    "와인": "와인", "wine": "와인",
    # 제한군(부정)
    "붉은 고기": "붉은 고기", "red_meats": "붉은 고기",
    "버터/마가린": "버터/마가린", "butter_margarine": "버터/마가린",
    "치즈": "치즈", "cheese": "치즈",
    "과자/디저트": "과자/디저트", "pastries_sweets": "과자/디저트",
    "튀김/패스트푸드": "튀김/패스트푸드", "fried_fast_food": "튀김/패스트푸드",
}

# 이모지 매핑(카테고리 → 이모지). 키는 "한국어 표준 라벨" 기준.
CATEGORY_EMOJI = {
    "녹색 잎채소": "🥬",
    "기타 채소": "🥦",
    "견과류": "🥜",
    "베리류": "🫐",
    "콩/두류": "🫘",
    "통곡물": "🌾",
    "생선": "🐟",
    "가금류": "🍗",
    "올리브유": "🫒",
    "와인": "🍷",
    "붉은 고기": "🥩",
    "버터/마가린": "🧈",
    "치즈": "🧀",
    "과자/디저트": "🍰",
    "튀김/패스트푸드": "🍟",
}

POSITIVE_ORDER = ["녹색 잎채소","기타 채소","견과류","베리류","콩/두류","통곡물","생선","가금류","올리브유","와인"]
NEGATIVE_ORDER = ["붉은 고기","버터/마가린","치즈","과자/디저트","튀김/패스트푸드"]

def _emoji_from_categories(categories:list, fallback_food_name:str=""):
    """
    categories에는 한국어/영문 키가 혼재할 수 있음.
    1) 모든 값을 한국어 표준 라벨로 정규화
    2) 긍정 카테고리 우선 → 부정 카테고리로 이모지 선택
    3) 없으면 음식 이름 기반 휴리스틱
    """
    if not categories:
        categories = []
    # 1) 표준 라벨로 정규화
    canon = []
    for c in categories:
        if c in MIND_CATEGORIES:
            canon.append(MIND_CATEGORIES[c])

    # 2) 우선순위에 따라 선택
    for cat in POSITIVE_ORDER:
        if cat in canon:
            return CATEGORY_EMOJI.get(cat, "")
    for cat in NEGATIVE_ORDER:
        if cat in canon:
            return CATEGORY_EMOJI.get(cat, "")

    # 3) 휴리스틱(음식 이름 기반)
    n = (fallback_food_name or "").lower()
    k = (fallback_food_name or "")
    heuristics = [
        (["샐러드","salad"], "🥗"),
        (["연어","고등어","참치","생선","fish","salmon","mackerel","tuna"], "🐟"),
        (["닭","치킨","가슴살","poultry","chicken"], "🍗"),
        (["소고기","돼지고기","양고기","스테이크","beef","pork","lamb","steak"], "🥩"),
        (["두부","콩","렌즈콩","병아리콩","tofu","bean","lentil","chickpea"], "🫘"),
        (["현미","귀리","오트","퀴노아","통곡물","oat","quinoa","brown rice","whole"], "🌾"),
        (["치즈","cheese"], "🧀"),
        (["버터","마가린","butter","margarine"], "🧈"),
        (["튀김","감자튀김","너겟","패스트푸드","햄버거","fried","fries","burger","nugget"], "🍟"),
        (["과자","디저트","케이크","쿠키","초콜릿","아이스크림","dessert","cookie","cake","choco","ice cream"], "🍰"),
        (["베리","블루베리","딸기","berry","blueberry","strawberry"], "🫐"),
        (["올리브","olive"], "🫒"),
        (["와인","wine"], "🍷"),
        (["채소","시금치","상추","케일","veg","vegetable","leafy"], "🥬"),
        (["브로콜리","당근","토마토","broccoli","carrot","tomato"], "🥦"),
        (["견과","아몬드","호두","캐슈","nut","almond","walnut","cashew"], "🥜"),
    ]
    for keys, emo in heuristics:
        for t in keys:
            if t in n or t in k:
                return emo
    return ""

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
            time.sleep(backoff_base * (2 ** i))
    logging.exception("Gemini call failed after retries: %s", last_err)
    return None

# ---------- 끼니명 표준화 ----------
def _normalize_meal_type(value: str) -> str:
    if not value:
        return "아침"
    v = value.strip().lower()
    mapping = {
        "아침": "아침", "morning": "아침", "breakfast": "아침",
        "점심": "점심", "lunch": "점심",
        "저녁": "저녁", "dinner": "저녁", "석식": "저녁",
        "간식": "간식", "스낵": "간식", "snack": "간식"
    }
    return mapping.get(v, value)

# ---------- 음식 추출 (첫 번째 코드 프롬프트) ----------
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

# ---------- MIND 점수 (첫 번째 코드 프롬프트) ----------
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
    
    data = {}
    if text:
        try:
            cleaned_text = re.sub(r"```(?:json)?|```", "", text, flags=re.DOTALL).strip()
            data = json.loads(cleaned_text)
        except json.JSONDecodeError:
            try:
                match = re.search(r'\{.*\}', text, re.DOTALL)
                if match:
                    data = json.loads(match.group(0))
            except Exception as e:
                logging.error("Failed to parse JSON from Gemini response: %s | Error: %s", text, e)
    
    logging.info(f"Gemini raw response: {text}")
    logging.info(f"Parsed data: {data}")

    items = data.get("items", []) if isinstance(data, dict) else []
    notes = data.get("notes", "") if isinstance(data, dict) else ""
    recommendation = data.get("recommendation", "")

    meal_score_total = 0.0
    valid_item_count = 0
    
    for it in items:
        score_val = it.get("score")
        if isinstance(score_val, (int, float)):
            score = max(0, min(100, int(score_val)))
            meal_score_total += score
            valid_item_count += 1
            it["score"] = score
        else:
            logging.warning(f"Invalid score value for food '{it.get('food')}': {score_val}")
            it["score"] = 0

        # 화이트리스트 필터(한/영 모두 허용)
        it["categories"] = [c for c in it.get("categories", []) if c in MIND_CATEGORIES]
        
    denom = max(1, valid_item_count)
    final_meal_score = round(meal_score_total / denom, 1)

    logging.info(f"Calculated final meal score: {final_meal_score}")

    return {"items": items, "meal_score": final_meal_score, "notes": notes, "recommendation": recommendation}

# ---------- [1] 음식 검색: 첫 번째 프롬프트 흐름 재사용 + 이모지 매핑 ----------
@chat_meal_bp.route('/foods/search', methods=['POST'])
def search_food_with_gemini():
    """
    입력(JSON): {"query":"연어 샐러드", "meal_type":"점심"}  # meal_type 선택
    출력(JSON): [ {"name":"연어 샐러드","score":90,"note":"...", "emoji":"🐟"}, ... ]
    내부 로직:
      1) extract_food_names(query)
      2) score_foods_mind(foods, meal_type)
      3) 카테고리 기반 이모지 자동 매핑 (없으면 휴리스틱)
    """
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    meal_type = data.get("meal_type", "")

    # 항상 배열 반환(클라 파싱 안정성)
    if not query:
        return jsonify([]), 200

    # 1) 음식명 추출 (첫 번째 코드 프롬프트 재사용)
    foods = extract_food_names(query)
    if not foods:
        foods = [query]  # 단일 항목으로 간주

    # 2) MIND 점수 산출 (첫 번째 코드 프롬프트 재사용)
    mind = score_foods_mind(foods, meal_type)

    # 3) 검색 응답 포맷: [{name, score, note, emoji}]
    out = []
    for it in mind.get("items", []):
        name = it.get("food", "")
        note = it.get("note", "")
        score_val = it.get("score", 0)
        try:
            score = int(float(score_val))
        except Exception:
            score = 0
        score = max(0, min(100, score))

        # 이모지: 카테고리 → 표준 라벨 정규화 → 매핑
        emoji = _emoji_from_categories(it.get("categories", []), fallback_food_name=name)
        out.append({"name": name, "score": score, "note": note, "emoji": emoji})

    return jsonify(out), 200

# ---------- [2] 수기 추가 ----------
@chat_meal_bp.route("/meals/add", methods=["POST"])
def add_meal_record():
    data = request.get_json(silent=True) or {}
    nickname     = data.get("nickname")
    meal_type_in = data.get("meal_type")
    food_details = data.get("food_details") or {}
    date_str     = data.get("date")  # 선택: 'YYYY-MM-DD'

    meal_type = _normalize_meal_type(meal_type_in)

    if not all([nickname, meal_type, food_details]):
        return jsonify({"error": "Missing fields"}), 400

    try:
        score_raw = food_details.get("score", 0)
        try:
            score_val = float(score_raw)
        except Exception:
            score_val = 0.0

        if date_str:
            try:
                ts = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    hour=12, minute=0, second=0, microsecond=0
                )
            except Exception:
                ts = datetime.now()
        else:
            ts = datetime.now()

        name = (food_details.get("name") or "").strip()
        note = (food_details.get("note") or "").strip()

        meal_document = {
            "nickname":  nickname,
            "meal_type": meal_type,
            "message":   name,
            "image_url": None,
            "foods":     [name] if name else [],
            "mind": {
                "items": [{
                    "food":  name,
                    "score": score_val,
                    "note":  note,
                }],
                "meal_score": float(score_val),
                "notes": "Gemini AI 분석 기반 식사",
            },
            "timestamp": ts,
        }

        result   = mongo.db.diet_records.insert_one(meal_document)
        inserted = mongo.db.diet_records.find_one({"_id": result.inserted_id})

        inserted["_id"] = str(inserted["_id"])
        if isinstance(inserted.get("timestamp"), datetime):
            inserted["timestamp"] = inserted["timestamp"].isoformat()

        return jsonify(inserted), 201

    except Exception as e:
        print(f"[ERROR] Meal Add Error: {e}")
        return jsonify({"error": "Failed to record meal"}), 500

# ---------- [3] 삭제 ----------
@chat_meal_bp.route("/meals/delete/<record_id>", methods=["DELETE"])
def delete_meal_record(record_id):
    try:
        obj_id = ObjectId(record_id)
        result = mongo.db.diet_records.delete_one({"_id": obj_id})
        if result.deleted_count == 1:
            return jsonify({"success": True, "message": "Record deleted"}), 200
        else:
            return jsonify({"error": "Record not found"}), 404
    except Exception as e:
        print(f"[ERROR] Meal Delete Error: {e}")
        return jsonify({"error": "Failed to delete record"}), 500

# ---------- [4] 날짜/끼니별 조회 ----------
@chat_meal_bp.route('/meals/list', methods=['GET'])
def list_meals_by_day():
    nickname  = request.args.get('nickname')
    meal_type = request.args.get('meal_type')
    date_str  = request.args.get('date')   # 'YYYY-MM-DD'

    if not all([nickname, meal_type, date_str]):
        return jsonify([]), 200

    try:
        start = datetime.strptime(date_str, '%Y-%m-%d')
        end   = start + timedelta(days=1)

        cur = (mongo.db.diet_records
               .find({"nickname": nickname,
                      "meal_type": meal_type,
                      "timestamp": {"$gte": start, "$lt": end}})
               .sort("timestamp", 1))

        out = []
        for doc in cur:
            doc["_id"] = str(doc["_id"])
            ts = doc.get("timestamp")
            if isinstance(ts, datetime):
                doc["timestamp"] = ts.isoformat()
            out.append(doc)

        return jsonify(out), 200

    except Exception as e:
        print("[ERROR] meals/list:", e)
        return jsonify([]), 200 

# ---------- [5] 채팅형 분석: text | image_url | image_base64 ----------
@chat_meal_bp.route('/chat-meal', methods=['POST'])
def chat_meal():
    """
    요청(JSON 예시):
      - 텍스트: {"nickname":"bb","meal_type":"아침","message":"연어 샐러드 먹었어"}
      - 이미지 URL: {"nickname":"bb","meal_type":"점심","image_url":"https://.../img.jpg"}
      - 이미지 base64: {"nickname":"bb","meal_type":"저녁","image_base64":"...","image_mime":"image/jpeg"}

    응답(JSON):
      {
        "success": true,
        "foods": ["연어 샐러드", ...],
        "mind": { ... },
        "source": "text|image|image_base64"
      }
    """
    try:
        data = request.get_json(force=True)
        nickname  = data.get('nickname', 'test_user')
        message   = data.get('message', '')
        meal_type = data.get('meal_type', '')
        image_url = data.get('image_url', '')
        img_b64   = (data.get("image_base64") or "").strip()
        img_mime  = (data.get("image_mime") or "image/jpeg").split(";")[0].strip()

        foods = []
        source = "unknown"

        # 1) base64 이미지
        if img_b64:
            try:
                image_bytes = base64.b64decode(img_b64)
                foods = extract_foods_from_image_bytes(image_bytes, mime=img_mime)
                source = "image_base64"
            except Exception as e:
                logging.error("base64 decode error: %s", e)

        # 2) 이미지 URL
        elif image_url:
            r = requests.get(image_url, timeout=10)
            r.raise_for_status()
            mime = (r.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
            foods = extract_foods_from_image_bytes(r.content, mime=mime)
            source = "image"

        # 3) 텍스트
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
            "source": source,
            "timestamp": datetime.now()
        })

        return jsonify({"success": True, "foods": foods, "mind": mind_result, "source": source}), 200

    except Exception as e:
        import traceback
        logging.error("chat-meal fatal: %s\n%s", e, traceback.format_exc())
        return jsonify({
            "success": False,
            "foods": [],
            "mind": {"items": [], "meal_score": 0.0, "notes": ""},
            "source": "error"
        }), 200

