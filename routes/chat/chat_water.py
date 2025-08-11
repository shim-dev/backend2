from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from extensions import mongo

record_water_bp = Blueprint("record_water", __name__)

@record_water_bp.route("/record-water", methods=["POST"])
def record_water():
    data = request.get_json()
    nickname = data.get("nickname")
    cups = int(data.get("cups", 0))

    if not nickname or cups <= 0:
        return jsonify({"success": False, "error": "Invalid data"}), 400

    # 현재 시간 및 오늘 00시 기준 시간 구하기
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # 오늘 기록된 누적 수치 불러오기
    today_records = mongo.db.water_records.find({
        "nickname": nickname,
        "timestamp": {"$gte": today_start}
    })

    daily_total = sum(record["cups"] for record in today_records) + cups

    # 현재 기록 추가
    mongo.db.water_records.insert_one({
        "nickname": nickname,
        "timestamp": now,
        "cups": cups,
        "daily_total": daily_total
    })

    return jsonify({
        "success": True,
        "cups": cups,
        "daily_total": daily_total
    })
