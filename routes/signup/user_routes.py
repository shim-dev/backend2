from flask import Blueprint, request, jsonify
from extensions import mongo  # MongoDB 객체

user_bp = Blueprint('user', __name__)

@user_bp.route('/register', methods=['POST'])
def register_user():
    data = request.get_json()
    print("[DEBUG] Received:", data)

    # 필수 필드 목록
    required_fields = [
        "email", "password", "nickname", "birthdate", "gender",
        "heightCm", "weightKg", "activityLevel", "sleepHours", "caffeine", "alcohol"
    ]

    # 필드 누락 및 빈 값 검사
    for field in required_fields:
        if field not in data or data[field] in [None, "", []]:
            print(f"[ERROR] Missing or empty field: {field}")
            return jsonify({"error": f"'{field}' is missing or empty"}), 400

    try:
        # MongoDB에 사용자 정보 저장
        mongo.db.users.insert_one(data)
        return jsonify({"message": "User registered successfully"}), 201

    except Exception as e:
        print("[ERROR]", str(e))
        return jsonify({"error": "Database insert failed"}), 500
