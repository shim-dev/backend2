from flask import Blueprint, request, jsonify
from extensions import mongo
from datetime import datetime
from dotenv import load_dotenv
import os
import google.generativeai as genai
import requests
import base64

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

def extract_foods_from_image(image_url: str):
    prompt = "이 이미지를 분석해서 음식 이름만 리스트로 알려줘. 형식은 반드시 [\"음식1\", \"음식2\"] 형태로 응답해줘."

    # 1. 이미지 다운로드
    response = requests.get(image_url)
    if response.status_code != 200:
        print("❌ 이미지 다운로드 실패:", response.status_code)
        return []

    # 2. 이미지 바이너리 데이터
    image_bytes = response.content

    # 3. Gemini Vision 호출 (inline_data로 이미지 전달)
    vision_model = genai.GenerativeModel("gemini-2.5-flash")
    result = vision_model.generate_content([
        {"text": prompt},
        {
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(image_bytes).decode('utf-8')
            }
        }
    ])

    print("Gemini 응답:", result.text)
    try:
        food_list = eval(result.text.strip())
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
    image_url = data.get('image_url', '')

    # Gemini API 호출 → 텍스트 또는 이미지 기반 분석
    if image_url:
        food_list = extract_foods_from_image(image_url)
    else:
        food_list = extract_food_names(message)

    # MongoDB 저장
    mongo.db.diet_records.insert_one({
        "nickname": nickname,
        "meal_type": meal_type,
        "message": message,
        "image_url": image_url if image_url else None,
        "foods": food_list,
        "timestamp": datetime.now()
    })

    return jsonify({
        "success": True,
        "foods": food_list,
        "source": "image" if image_url else "text"
    })
