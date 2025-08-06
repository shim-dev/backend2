from flask import Blueprint, jsonify
from extensions import mongo  # mongo 객체 불러오기

keywords_bp = Blueprint('keywords', __name__)

@keywords_bp.route('/keywords', methods=['GET'])
def get_keywords():
    try:
        # keywords 컬렉션에서 keyword 필드만 가져오기 (_id 제외)
        keywords_cursor = mongo.db.keywords.find({}, {"_id": 0, "keyword": 1})
        keywords_list = [doc["keyword"] for doc in keywords_cursor]

        return jsonify({
            "status": "success",
            "keywords": keywords_list
        }), 200

    except Exception as e:
        print("[ERROR]", str(e))
        return jsonify({
            "status": "error",
            "message": "Failed to fetch keywords"
        }), 500

