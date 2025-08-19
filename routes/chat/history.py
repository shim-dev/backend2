from flask import Blueprint, request, jsonify
from extensions import mongo
from datetime import datetime # datetime 임포트 추가

main_routes = Blueprint('main_routes', __name__, url_prefix='/api')

@main_routes.route('/history', methods=['GET'])
def get_history():
    email = request.args.get("email")
    if not email:
        return jsonify({"error": "Email is required"}), 400

    user = mongo.db.users.find_one({"email": email})
    if not user:
        return jsonify({"error": "User not found in history route"}), 404
    
    nickname = user['nickname']

    records_cursor = mongo.db.diet_records.find(
        {'nickname': nickname}
    ).sort('timestamp', -1).limit(3)

    result_list = []
    for record in records_cursor:
        record['_id'] = str(record['_id'])
        
        if 'timestamp' in record and isinstance(record['timestamp'], datetime):
            # '2025-08-13T04:40:00.123Z' 와 같은 표준 형식으로 변환
            record['timestamp'] = record['timestamp'].isoformat() + "Z"

        result_list.append(record)

    return jsonify(result_list), 200
