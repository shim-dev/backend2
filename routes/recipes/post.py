# routes/post.py
from flask import Blueprint, request, jsonify
from datetime import datetime
from extensions import mongo

post_bp = Blueprint("post", __name__, url_prefix="/posts")

ALLOWED_DIFFICULTY = {"LOW", "MID", "HIGH"}
HARDCODED_NICKNAME = "test"  # TODO: JWT 붙이면 제거하고 user_id/닉네임 사용

def _now():
    return datetime.utcnow()

def _validate_post(data: dict):
    errors = {}

    # title
    title = (data.get("title") or "").strip()
    if not (1 <= len(title) <= 100):
        errors["title"] = "1~100자 필수"

    # content
    content = (data.get("content") or "").strip()
    if not (1 <= len(content) <= 5000):
        errors["content"] = "1~5000자 필수"

    # categories
    categories = data.get("categories", [])
    if categories:
        if not isinstance(categories, list):
            errors["categories"] = "문자열 배열이어야 함"
        elif len(categories) > 10 or any(not isinstance(c, str) or not c.strip() for c in categories):
            errors["categories"] = "빈 값 불가, 최대 10개"

    # time_min
    time_min = data.get("time_min")
    if time_min is not None:
        if not isinstance(time_min, int) or not (1 <= time_min <= 1440):
            errors["time_min"] = "1~1440 범위의 정수"

    # difficulty
    difficulty = data.get("difficulty")
    if difficulty is not None:
        if not isinstance(difficulty, str) or difficulty.upper() not in ALLOWED_DIFFICULTY:
            errors["difficulty"] = "LOW/MID/HIGH 중 하나"

    # images
    images = data.get("images", [])
    if images:
        if not isinstance(images, list) or any(not isinstance(u, str) or not u for u in images):
            errors["images"] = "URL 문자열 배열"

    return errors

@post_bp.route("", methods=["POST"])
def create_post():
    try:
        data = request.get_json(silent=True) or {}
        errors = _validate_post(data)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400

        doc = {
            "title": data["title"].strip(),
            "content": data["content"].strip(),
            "categories": data.get("categories", []),
            "time_min": data.get("time_min"),
            "difficulty": (data.get("difficulty") or "").upper() or None,
            "images": data.get("images", []),
            "nickname": HARDCODED_NICKNAME,  # TODO: 인증 붙이면 교체
            "created_at": _now(),
            "updated_at": _now(),
        }

        res = mongo.db.posts.insert_one(doc)
        doc["_id"] = str(res.inserted_id)
        return jsonify({"ok": True, "post": doc}), 201

    except Exception as e:
        # 로깅은 실제로 logger 사용 권장
        return jsonify({"ok": False, "error": "internal_error", "message": str(e)}), 500
