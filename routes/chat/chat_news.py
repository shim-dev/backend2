from flask import Blueprint, jsonify
import requests
import urllib.parse
import os
import google.generativeai as genai
import re
import html

news_bp = Blueprint("news", __name__)

# 환경 변수에서 키 로드
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
    raise EnvironmentError("NAVER API 키가 설정되지 않았습니다.")

# Gemini 설정
USE_GEMINI = False  # True로 바꾸면 요약도 포함
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

@news_bp.route("/news", methods=["POST"])
def get_antiaging_news():
    try:
        query = urllib.parse.quote("저속노화")
        url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=3&sort=date"
        
        headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
        }

        response = requests.get(url, headers=headers)
        data = response.json()

        news_list = []
        for item in data.get("items", []):
            title = clean_html_tags(item["title"])
            link = item["link"]

            news_list.append({
                "title": title,
                "url": link,
            })

        return jsonify({ "success": True, "news": news_list })

    except Exception as e:
        return jsonify({ "success": False, "error": str(e) }), 500

def clean_html_tags(text):
    text = re.sub("<.*?>", "", text)     # HTML 태그 제거
    return html.unescape(text)

def summarize_with_gemini(text):
    prompt = f"다음 뉴스 내용을 한 문장으로 요약해줘:\n{text}"
    try:
        response = model.generate_content(prompt)
        return response.candidates[0].content.parts[0].text.strip()
    except Exception as e:
        return "요약 실패"
