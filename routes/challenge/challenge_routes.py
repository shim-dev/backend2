import os
import base64
import uuid
import cloudinary
import cloudinary.uploader
from flask import send_from_directory
from werkzeug.utils import secure_filename

from flask import Blueprint, jsonify, request, abort, url_for, current_app
from extensions import mongo
from bson import ObjectId
from datetime import datetime
from PIL import Image
from io import BytesIO
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-pro")
cloudinary.config(cloudinary_url=os.getenv("CLOUDINARY_URL"))

challenge_bp = Blueprint('challenge', __name__, url_prefix='/api')

# ---- [테스트 모드 설정] ----
TEST_MODE = False             # 나중에 False로 바꾸면 원래대로 동작
TEST_NICKNAME = "chaelim"    # 테스트할 닉네임 (하드코딩)
# --------------------------

def get_nickname(req_nickname=None):
    """TEST_MODE가 True면 TEST_NICKNAME, 아니면 요청값 사용"""
    if TEST_MODE:
        return TEST_NICKNAME
    return req_nickname


# ------------------ 챌린지 생성 ------------------
@challenge_bp.route('/challenges/create', methods=['POST'])
def create_challenge():
    # multipart/form-data 요청 처리
    # multipart/form-data 요청 처리
    if request.content_type and request.content_type.startswith("multipart/form-data"):
        form = request.form
        file = request.files.get("image")
        if not file or file.filename == "":
            return jsonify({"error": "Image file is required"}), 400

        # ✅ Cloudinary 업로드 (서버 디스크 저장 X)
        res = cloudinary.uploader.upload(
            file,               # FileStorage 그대로 전달
            folder="challenges",
            resource_type="image"
        )
        image_url = res["secure_url"]      # 앱에서 쓸 공개 HTTPS URL
        public_id = res["public_id"]       # (선택) 추후 삭제/변경용

        challenge = {
            "title": form.get("title"),
            "description": form.get("description"),
            "image_url": image_url,         # ← 요거만 쓰면 됨
            "image_public_id": public_id,   # ← 선택 필드
            "points_reward": int(form.get("points_reward")),
            "max_participants": int(form.get("max_participants")),
            "start_date": form.get("start_date"),
            "end_date": form.get("end_date"),
            "goal_steps": int(form.get("goal_steps", 8000)),
            "participants": 0,
            "status": "active",
            "joined_users": []
        }

        result = mongo.db.challenges.insert_one(challenge)
        return jsonify({
            "message": "Challenge created (cloudinary)",
            "challenge_id": str(result.inserted_id),
            "image_url": image_url
        }), 201


    return jsonify({"error": "Invalid content type"}), 400


# ------------------ 챌린지 목록 ------------------
@challenge_bp.route('/challenges', methods=['GET'])
def get_challenges():
    try:
        filter_type = request.args.get("filter", "all")
        nickname = get_nickname(request.args.get("nickname"))  # 유연하게 처리

        if filter_type == "my":
            user = mongo.db.users.find_one({"nickname": nickname})
            if not user or "joined_challenges" not in user or not user["joined_challenges"]:
                return jsonify({"message": "참여 중인 챌린지가 없습니다."}), 200
            challenge_ids = [ObjectId(cid) for cid in user["joined_challenges"]]
            challenges = list(mongo.db.challenges.find({"_id": {"$in": challenge_ids}}))
        else:
            challenges = list(mongo.db.challenges.find())

        for ch in challenges:
            ch["_id"] = str(ch["_id"])
            # joined 여부
            ch["joined"] = False
            if nickname and "joined_users" in ch:
                ch["joined"] = nickname in ch["joined_users"]
            # multipart 저장본: image_path -> image_url
            if ch.get("image_path") and not ch.get("image_url"):
                rel = ch["image_path"].replace("\\", "/")          
                ch["image_url"] = url_for('static', filename=rel, _external=True)

        return jsonify(challenges), 200

    except Exception as e:
        print("[ERROR]", str(e))
        return jsonify({"error": "Failed to fetch challenges"}), 500


# ------------------ 챌린지 상세 ------------------
@challenge_bp.route('/challenges/<challenge_id>', methods=['GET'])
def get_challenge_detail(challenge_id):
    try:
        challenge = mongo.db.challenges.find_one({"_id": ObjectId(challenge_id)})
        if not challenge:
            abort(404, description="Challenge not found")

        challenge["_id"] = str(challenge["_id"])

        # multipart 저장본: image_path -> image_url
        if challenge.get("image_path") and not challenge.get("image_url"):
            rel = challenge["image_path"].replace("\\", "/")     
            challenge["image_url"] = url_for('static', filename=rel, _external=True)


        return jsonify(challenge), 200
    except Exception as e:
        print("[ERROR]", str(e))
        return jsonify({"error": "Failed to fetch challenge detail"}), 500


# ------------------ 챌린지 참여 ------------------
@challenge_bp.route("/challenges/join", methods=["POST"])
def join_challenge():
    data = request.get_json()
    print("[DEBUG] 받은 데이터:", data)
    if not data:
        return jsonify({"error": "No JSON received"}), 400

    nickname = data.get("nickname")
    challenge_id = data.get("challenge_id")

    if not nickname or not challenge_id:
        return jsonify({"error": "Missing fields"}), 400

    try:
        # 1. 챌린지 정보 조회
        challenge = mongo.db.challenges.find_one({"_id": ObjectId(challenge_id)})
        if not challenge:
            return jsonify({"error": "챌린지를 찾을 수 없습니다."}), 404

        entry_fee = challenge.get("points_reward", 0)

        # 2. 사용자 정보 조회
        user = mongo.db.users.find_one({"nickname": nickname})
        if not user:
            return jsonify({"error": "사용자를 찾을 수 없습니다."}), 404

        user_point = user.get("point", 0)
        print(f"[DEBUG] user_point: {user_point}, entry_fee: {entry_fee}")

        if user_point < entry_fee:
            return jsonify({"error": "포인트가 부족합니다."}), 400

        # 3. 이미 참여한 챌린지인지 확인
        print(f"[DEBUG] joined_users: {challenge.get('joined_users', [])}")
        if nickname in challenge.get("joined_users", []):
            return jsonify({"error": "이미 참여한 챌린지입니다."}), 400

        # 4. 챌린지 참가 처리
        mongo.db.challenges.update_one(
            {"_id": ObjectId(challenge_id)},
            {
                "$addToSet": {"joined_users": nickname},
                "$inc": {"participants": 1}
            }
        )

        mongo.db.users.update_one(
            {"nickname": nickname},
            {
                "$addToSet": {"joined_challenges": challenge_id},
                "$inc": {"point": -entry_fee}
            }
        )

        # 5. 포인트 기록 저장
        mongo.db.point_history.insert_one({
            "nickname": nickname,
            "type": "use",
            "description": "챌린지 참여",
            "points": entry_fee,
            "date": datetime.now().strftime("%Y-%m-%d")
        })

        # 6. 참가 정보 별도 저장 (보상 위해)
        mongo.db.challenge_participation.insert_one({
            "nickname": nickname,
            "challenge_id": challenge_id,
            "entry_fee": entry_fee,
            "joined_at": datetime.now().strftime("%Y-%m-%d")
        })

        return jsonify({
            "message": f"{nickname} 님이 챌린지에 성공적으로 참여했고, {entry_fee}P가 차감되었습니다."
        }), 201

    except Exception as e:
        print("[ERROR]", str(e))
        return jsonify({"error": "챌린지 참가 중 오류 발생"}), 500


# ------------------ 유저 포인트 요약 ------------------
@challenge_bp.route('/user-info', methods=['GET'])
def get_user_info():
    try:
        nickname = get_nickname(request.args.get("nickname"))
        user = mongo.db.users.find_one({"nickname": nickname})
        if not user:
            return jsonify({"error": "User not found"}), 404

        return jsonify({
            "nickname": user.get("nickname", ""),
            "point": user.get("point", 0)
        }), 200

    except Exception as e:
        print("[ERROR]", str(e))
        return jsonify({"error": "Failed to fetch user info"}), 500


# ------------------ 포인트 내역 ------------------
@challenge_bp.route('/points/history/<nickname>', methods=['GET'])
def get_point_history(nickname):
    try:
        history = list(mongo.db.point_history.find({"nickname": nickname}))
        for item in history:
            item["_id"] = str(item["_id"])
        return jsonify(history), 200
    except Exception as e:
        print("[ERROR]", str(e))
        return jsonify({"error": "Failed to fetch point history"}), 500


# ------------------ 인증 현황 ------------------
@challenge_bp.route("/challenge_verification/status", methods=["GET"])
def get_verification_status():
    challenge_id = request.args.get("challenge_id")
    nickname = request.args.get("nickname")

    verification = mongo.db.challenge_verification.find_one({
        "challenge_id": challenge_id,
        "nickname": nickname
    })

    certified_days = verification.get("certified_days", []) if verification else []

    # start_date 추가
    challenge = mongo.db.challenges.find_one({"_id": ObjectId(challenge_id)})
    start_date = challenge.get("start_date") if challenge else None

    return jsonify({
        "certified_days": certified_days,
        "start_date": start_date,
        "title": challenge.get("title") if challenge else None,
        "goal_steps": challenge.get("goal_steps", 8000) if challenge else 8000,
        "description": challenge.get("description") if challenge else None
    })


# ------------------ 환급 신청 ------------------
@challenge_bp.route('/refund', methods=['POST'])
def apply_refund():
    try:
        data = request.get_json()
        nickname = data.get("nickname")
        bank = data.get("bank")
        account_number = data.get("account_number")
        account_holder = data.get("account_holder")
        refund_amount = data.get("refund_amount")

        if not all([nickname, bank, account_number, account_holder, refund_amount]):
            return jsonify({"error": "모든 필드를 입력해주세요."}), 400

        user = mongo.db.users.find_one({"nickname": nickname})
        if not user:
            return jsonify({"error": "사용자를 찾을 수 없습니다."}), 404

        current_points = user.get("point", 0)
        if refund_amount > current_points:
            return jsonify({"error": "포인트가 부족합니다."}), 400

        # 1. 환급 요청 저장
        mongo.db.refund_requests.insert_one({
            "nickname": nickname,
            "bank": bank,
            "account_number": account_number,
            "account_holder": account_holder,
            "refund_amount": refund_amount,
            "status": "pending",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

        # 2. 포인트 차감
        mongo.db.users.update_one(
            {"nickname": nickname},
            {"$inc": {"point": -refund_amount}}
        )

        # 3. 포인트 기록 추가
        mongo.db.point_history.insert_one({
            "nickname": nickname,
            "type": "use",
            "description": "포인트 환급 신청",
            "points": refund_amount,
            "date": datetime.now().strftime("%Y-%m-%d")
        })

        return jsonify({"message": "환급 신청이 완료되었습니다."}), 201

    except Exception as e:
        print("[ERROR]", str(e))
        return jsonify({"error": "환급 신청 처리 중 오류 발생"}), 500


# ------------------ 이미지 인증 ------------------
@challenge_bp.route("/challenges/verify", methods=["POST"])
def verify_challenge_image():
    data = request.get_json()
    base64_image = data.get("image")
    nickname = data.get("nickname")
    challenge_id = data.get("challenge_id")
    today_day = data.get("today_day")

    if not base64_image or not nickname or not challenge_id:
        return jsonify({"error": "필수 항목 누락"}), 400

    # ✅ 챌린지에서 목표 걸음수 가져오기 (클라에서 안 받음!)
    ch = mongo.db.challenges.find_one({"_id": ObjectId(challenge_id)})
    if not ch:
        return jsonify({"error": "챌린지를 찾을 수 없습니다."}), 404
    goal_steps = int(ch.get("goal_steps", 8000))

    # 디코딩 후 임시 저장
    image_bytes = base64.b64decode(base64_image)
    image = Image.open(BytesIO(image_bytes))

    upload_folder = "uploads"
    os.makedirs(upload_folder, exist_ok=True)
    save_path = os.path.join(upload_folder, f"{nickname}_{challenge_id}_{today_day}.jpg")
    image.save(save_path)

    # LLM으로 걷기 수 판단
    extracted_steps = extract_steps_with_llm(save_path)
    print(f"[DEBUG] 추출된 걸음 수: {extracted_steps} / 목표 걸음 수: {goal_steps}")

    if extracted_steps < goal_steps:
        return jsonify({"success": False, "message": "걸음 수 부족"}), 200

    # 인증 성공 날짜 기록
    mongo.db.challenge_verification.update_one(
        {"nickname": nickname, "challenge_id": challenge_id},
        {"$addToSet": {"certified_days": today_day}},
        upsert=True
    )
    return jsonify({"success": True, "message": "인증 성공"}), 200



def extract_steps_with_llm(image_path):
    prompt = """
    이 이미지가 만보기 앱 캡처로 보인다면 해당 이미지에 기록된 걸음 수를 숫자로 추출해주세요.
    숫자만 출력하세요. 다른 말은 하지 마세요.
    """
    img = Image.open(image_path)
    try:
        response = model.generate_content([prompt, img])
        result = response.text.strip()
        return int("".join(filter(str.isdigit, result)))
    except Exception as e:
        print(f"[ERROR] 걸음 수 추출 실패: {e}")
        return 0


# ------------------ 보상 ------------------
@challenge_bp.route("/challenges/reward", methods=["POST"])
def get_reward():
    data = request.get_json()
    nickname = data.get("nickname")
    challenge_id = data.get("challenge_id")

    if not nickname or not challenge_id:
        return jsonify({"error": "필수 정보 누락"}), 400

    verification = mongo.db.challenge_verification.find_one({"nickname": nickname, "challenge_id": challenge_id})
    if not verification or len(verification.get("certified_days", [])) < 28:
        return jsonify({"error": "28일 모두 인증해야 보상 받을 수 있어요."}), 400

    already_rewarded = mongo.db.rewards.find_one({"nickname": nickname, "challenge_id": challenge_id})
    if already_rewarded:
        return jsonify({"error": "이미 보상을 받았습니다."}), 400

    participation = mongo.db.challenge_participation.find_one({"nickname": nickname, "challenge_id": challenge_id})
    reward_points = participation["entry_fee"]

    mongo.db.points.insert_one({
        "nickname": nickname,
        "type": "earn",
        "amount": reward_points,
        "description": f"챌린지 보상 - {challenge_id}",
        "date": datetime.now()
    })

    mongo.db.rewards.insert_one({
        "nickname": nickname,
        "challenge_id": challenge_id,
        "date": datetime.now()
    })

    return jsonify({"message": "보상 지급 완료!"})
