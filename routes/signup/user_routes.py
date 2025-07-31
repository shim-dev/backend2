from flask import Blueprint, request, jsonify
from extensions import mongo  # MongoDB 객체
import bcrypt  # 비밀번호 해싱

user_bp = Blueprint('user', __name__)

@user_bp.route('/register', methods=['POST'])
def register_user():
    data = request.get_json()
    print("[DEBUG] Received:", data)

    required_fields = [
        "email", "password", "nickname", "birthdate", "gender",
        "heightCm", "weightKg", "activityLevel", "sleepHours", "caffeine", "alcohol"
    ]

    for field in required_fields:
        if field not in data or data[field] in [None, "", []]:
            print(f"[ERROR] Missing or empty field: {field}")
            return jsonify({"error": f"'{field}' is missing or empty"}), 400

    try:
        # 비밀번호 해싱 처리
        plain_password = data["password"]
        hashed_password = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
        data["password"] = hashed_password.decode("utf-8")  # byte → str

        # MongoDB에 사용자 정보 저장
        mongo.db.users.insert_one(data)
        return jsonify({"message": "User registered successfully"}), 201

    except Exception as e:
        print("[ERROR]", str(e))
        return jsonify({"error": "Database insert failed"}), 500

# 이메일 중복 확인
@user_bp.route('/check-email', methods=['POST'])
def check_email():
    data = request.get_json()
    email = data.get("email")

    if not email:
        return jsonify({"error": "Email is required"}), 400

    user = mongo.db.users.find_one({"email": email})
    if user:
        return jsonify({"exists": True}), 200
    else:
        return jsonify({"exists": False}), 200
   
# 닉네임 중복 확인
@user_bp.route('/check-nickname', methods=['POST'])
def check_nickname():
    data = request.get_json()
    nickname = data.get("nickname")

    if not nickname:
        return jsonify({"error": "Nickname is required"}), 400

    user = mongo.db.users.find_one({"nickname": nickname})
    if user:
        return jsonify({"exists": True}), 200
    else:
        return jsonify({"exists": False}), 200

   
@user_bp.route('/login', methods=['POST'])
def login_user():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    user = mongo.db.users.find_one({"email": email})
    if user and bcrypt.checkpw(password.encode("utf-8"), user["password"].encode("utf-8")):
        return jsonify({
            "message": "Login successful",
            "nickname": user["nickname"],
            "email": user["email"]
        }), 200
    else:
        return jsonify({"error": "Invalid email or password"}), 401
