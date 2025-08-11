from flask import Blueprint, request, jsonify
from extensions import mongo
from datetime import datetime

search_history_bp = Blueprint('search_history', __name__)

@search_history_bp.route('/search-history/add', methods=['POST'])
def add_search_history():
    data = request.json
    keyword = data.get('keyword', '').strip()
    if not keyword:
        return jsonify({"status": "error", "message": "Keyword required"}), 400

    # 중복 방지 (같은 단어는 기존 삭제 후 다시 저장)
    mongo.db.search_history.delete_many({"keyword": keyword})

    mongo.db.search_history.insert_one({
        "keyword": keyword,
        "created_at": datetime.utcnow()
    })
    return jsonify({"status": "success"})


@search_history_bp.route('/search-history/list', methods=['GET'])
def get_search_history():
    records = list(mongo.db.search_history.find().sort("created_at", -1))
    for r in records:
        r["_id"] = str(r["_id"])
        if "created_at" in r:
            r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")  # ✅ 문자열 변환
    return jsonify(records)


@search_history_bp.route('/search-history/delete', methods=['DELETE'])
def delete_search_item():
    keyword = request.args.get('keyword', '')
    mongo.db.search_history.delete_many({"keyword": keyword})
    return jsonify({"status": "success"})


@search_history_bp.route('/search-history/clear', methods=['DELETE'])
def clear_search_history():
    mongo.db.search_history.delete_many({})
    return jsonify({"status": "success"})
