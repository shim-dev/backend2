from flask import Blueprint, jsonify, request
from extensions import mongo  # mongo 객체 불러오기

search_bp = Blueprint('search', __name__)

@search_bp.route('/recipes/search', methods=['GET'])
def search_recipes():
    try:
        # 쿼리 파라미터에서 검색어 가져오기
        keyword = request.args.get('keyword', '').strip()

        if not keyword:
            return jsonify({
                "status": "error",
                "message": "Keyword is required"
            }), 400

        # name 또는 desc 필드에 keyword가 포함된 데이터 검색 (대소문자 무시)
        query = {
            "$or": [
                {"name": {"$regex": keyword, "$options": "i"}},
                {"desc": {"$regex": keyword, "$options": "i"}},
            ]
        }

        # MongoDB에서 레시피 데이터 가져오기 (_id 제외)
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
        })

        # 결과 리스트로 변환
        recipes_list = list(recipes_cursor)
        print(recipes_list)
        return jsonify(recipes_list), 200

    except Exception as e:
        print("[ERROR]", str(e))
        return jsonify({
            "status": "error",
            "message": "Failed to fetch recipes"
        }), 500
