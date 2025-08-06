from flask import Blueprint, jsonify, request
from extensions import mongo  # mongo 객체 불러오기

search_bp = Blueprint('search', __name__)

@search_bp.route('/recipes/search', methods=['GET'])
def search_recipes():
    try:
        keyword = request.args.get('keyword', '').strip()
        sort_by = request.args.get('sort', 'latest')  # 기본값 latest

        if not keyword:
            return jsonify({
                "status": "error",
                "message": "Keyword is required"
            }), 400

        # 검색 조건
        query = {
            "$or": [
                {"name": {"$regex": keyword, "$options": "i"}},
                {"desc": {"$regex": keyword, "$options": "i"}},
            ]
        }

        # 정렬 조건
        if sort_by == 'views':
            sort_option = [("views", -1)]  # 조회순
        else:
            sort_option = [("_id", -1)]  # 최신순 (기본값)

        # MongoDB 조회 + 정렬
        recipes_cursor = mongo.db.recipes.find(query, {
            "_id": 1,
            "name": 1,
            "keywords": 1,
            "desc": 1,
            "time": 1,
            "level": 1,
            "serving": 1,
            "imageUrl": 1,
            "book": 1,
            "steps": 1,
            "ingredients": 1,
            "score": 1,
            "views": 1
        }).sort(sort_option)

        recipes_list = list(recipes_cursor)

        # ObjectId → 문자열 변환
        for recipe in recipes_list:
            recipe["_id"] = str(recipe["_id"])

        return jsonify(recipes_list), 200

    except Exception as e:
        print("[ERROR]", str(e))
        return jsonify({
            "status": "error",
            "message": "Failed to fetch recipes"
        }), 500
