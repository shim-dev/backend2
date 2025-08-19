# routes/signup/user_routes.py
from flask import Blueprint, request, jsonify
from extensions import mongo  # MongoDB 객체
import bcrypt  # 비밀번호 해싱

user_bp = Blueprint('user', __name__)

def _json():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}

def _norm_email(email: str) -> str:
    return (email or "").strip().lower()

def _required(data: dict, fields: list[str]):
    for f in fields:
        if f not in data or data[f] in (None, "", []):
            return f
    return None
    
@user_bp.route('/register', methods=['POST'])
def register_user():
    data = _json()
    print("[DEBUG] /register Received:", data)

    required_fields = [
        "email", "password", "nickname", "birthdate", "gender",
        "heightCm", "weightKg", "activityLevel", "sleepHours", "caffeine", "alcohol"
    ]
    missing = _required(data, required_fields)
    if missing:
        print(f"[ERROR] Missing or empty field: {missing}")
        return jsonify({"error": f"'{missing}' is missing or empty"}), 400

    try:
        # 이메일 정규화
        data["email"] = _norm_email(data["email"])

        # 비밀번호 해싱
        plain_password = str(data["password"])
        hashed_password = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
        data["password"] = hashed_password.decode("utf-8")  # byte → str

        # MongoDB 저장
        mongo.db.users.insert_one(data)
        return jsonify({"message": "User registered successfully"}), 201

    except Exception as e:
        print("[ERROR] /register:", str(e))
        return jsonify({"error": "Database insert failed"}), 500

@user_bp.route('/check-email', methods=['POST'])
def check_email():
    data = _json()
    email = _norm_email(data.get("email", ""))

    if not email:
        return jsonify({"error": "Email is required"}), 400

    user = mongo.db.users.find_one({"email": email})
    return jsonify({"exists": bool(user)}), 200

@user_bp.route('/check-nickname', methods=['POST'])
def check_nickname():
    data = _json()
    nickname = (data.get("nickname") or "").strip()

    if not nickname:
        return jsonify({"error": "Nickname is required"}), 400

    user = mongo.db.users.find_one({"nickname": nickname})
    return jsonify({"exists": bool(user)}), 200


@user_bp.route('/login', methods=['POST'])
def login_user():
    data = _json()
    email = _norm_email(data.get("email"))
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    user = mongo.db.users.find_one({"email": email})
    if not user:
        return jsonify({"error": "Invalid email or password"}), 401

    stored = str(user.get("password", ""))
    is_valid = False
    try:
        # bcrypt 포맷($2b$...)이면 해시 검증
        if stored.startswith("$2b$") or stored.startswith("$2a$"):
            is_valid = bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
        else:
            # 구버전(평문) 임시 비교
            is_valid = (password == stored)
    except Exception as e:
        print("[WARN] bcrypt check exception:", e)
        is_valid = (password == stored)

    if not is_valid:
        return jsonify({"error": "Invalid email or password"}), 401

    return jsonify({
        "message": "Login successful",
        "nickname": user.get("nickname", ""),
        "email": user.get("email", "")
    }), 200


@user_bp.route('/me', methods=['GET'])
def get_me():
    """로그인 사용자 기본 정보 반환: URL 파라미터 email 사용"""
    email = _norm_email(request.args.get("email"))
    if not email:
        return jsonify({"error": "Email parameter is missing"}), 400

    print(f"[DEBUG] '/me' 요청 받음. 이메일: {email}")
    print(f"[DEBUG] 현재 사용 중인 DB 이름: {mongo.db.name}")

    user = mongo.db.users.find_one({"email": email})
    print(f"[DEBUG] DB에서 찾은 사용자: {user}")

    if not user:
        return jsonify({"error": "User not found"}), 404

    # 비밀번호 제거 및 _id 문자열화
    user.pop("password", None)
    user_id = str(user.get("_id")) if user.get("_id") else None

    return jsonify({
        "id": user_id,
        "nickname": user.get("nickname", ""),
        "email": user.get("email", "")
    }), 200

