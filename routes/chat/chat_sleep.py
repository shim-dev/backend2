from flask import Blueprint, request, jsonify
from datetime import datetime
from extensions import mongo

record_sleep_bp = Blueprint("record_sleep", __name__)

@record_sleep_bp.route("/record-sleep", methods=["POST"])
def record_sleep():
    data = request.get_json()
    nickname = data.get("nickname")
    hours = data.get("hours", 0)
    minutes = data.get("minutes", 0)

    if not nickname or (not isinstance(hours, int)) or (not isinstance(minutes, int)):
        return jsonify({"success": False, "error": "Invalid input"}), 400

    total_minutes = hours * 60 + minutes
    now = datetime.now()

    mongo.db.sleep_records.insert_one({
        "nickname": nickname,
        "timestamp": now,
        "hours": hours,
        "minutes": minutes,
        "total_minutes": total_minutes
    })

    return jsonify({
        "success": True,
        "total_minutes": total_minutes
    })
