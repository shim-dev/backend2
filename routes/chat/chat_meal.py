from flask import Blueprint, request, jsonify
from extensions import mongo
from datetime import datetime
from dotenv import load_dotenv
import os
import google.generativeai as genai

chat_meal_bp = Blueprint('chat_meal', __name__)

# Gemini 설정
load_dotenv()
genai.configure(api_key="AIzaSyDUM9U-2p73C2HTHST2rz_p1mlDzZaJ0GI")
model = genai.GenerativeModel("gemini-2.5-pro")

def extract_food_names(message: str):
    prompt = f"""
다음 문장에서 음식 이름만 리스트로 뽑아줘.
형식: ["음식1", "음식2"] 로 응답해야 해.  
문장: "{message}"
"""
    response = model.generate_content(prompt)
    print("Gemini 응답:", response.text)
    try:
        food_list = eval(response.text.strip())
        if isinstance(food_list, list):
            return food_list
    except:
        pass
    return []

@chat_meal_bp.route('/chat-meal', methods=['POST'])
def chat_meal():
    data = request.get_json()
    nickname = data.get('nickname', 'test_user') 
    message = data.get('message', '')
    meal_type = data.get('meal_type', '')

    # Gemini API 호출 → 음식명 추출
    food_list = extract_food_names(message)

    # MongoDB 저장
    mongo.db.diet_records.insert_one({
        "nickname": nickname,
        "meal_type": meal_type,
        "message": message,
        "foods": food_list,
        "timestamp": datetime.now()
    })

    return jsonify({
        "success": True,
        "foods": food_list
    })
