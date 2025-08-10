from flask import Blueprint, jsonify
from bson import ObjectId
from extensions import mongo  # mongo 객체 불러오기

view_bp = Blueprint('view', __name__)

@view_bp.route('/recipes/view/<recipe_id>', methods=['POST'])
def increase_recipe_view(recipe_id):
    try:
        # MongoDB에서 해당 레시피 찾고 views 1 증가
        result = mongo.db.recipes.update_one(
            {"_id": ObjectId(recipe_id)},
            {"$inc": {"views": 1}}
        )

        if result.matched_count == 0:
            return jsonify({
                "status": "error",
                "message": "Recipe not found"
            }), 404

        return jsonify({
            "status": "success",
            "message": "View count increased"
        }), 200

    except Exception as e:
        print("[ERROR]", str(e))
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
