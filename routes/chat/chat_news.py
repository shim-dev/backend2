from flask import Blueprint, request, jsonify
import os
import json
import google.generativeai as genai

genai.configure(api_key="AIzaSyDUM9U-2p73C2HTHST2rz_p1mlDzZaJ0GI")

news_bp = Blueprint("news", __name__)

@news_bp.route("/news", methods=["POST"])
def get_antiaging_news():
    try:
        result = generate_news_summaries()
        return jsonify({ "success": True, "news": result })
    except Exception as e:
        return jsonify({ "success": False, "error": str(e) }), 500

def generate_news_summaries():
    prompt = (
        "저속노화(anti-aging, longevity)에 관한 최신 뉴스 기사 3개를 알려줘.\n"
        "각 뉴스는 제목(title), 요약(summary), 링크(url)를 포함해서 JSON 배열 형태로 반환해줘.\n"
        "예시: [{\"title\": ..., \"summary\": ..., \"url\": ...}]"
    )

    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)

    # 전체 응답 텍스트
    text = response.candidates[0].content.parts[0].text.strip()

    # JSON 블럭만 추출
    import re
    match = re.search(r"```json\s*(\[.*?\])\s*```", text, re.DOTALL)
    if not match:
        raise ValueError("JSON 블럭을 찾을 수 없습니다.")

    json_text = match.group(1).strip()

    print("[DEBUG] 추출된 JSON 블럭:\n", json_text)

    return json.loads(json_text)
