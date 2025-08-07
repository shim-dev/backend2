from flask import Blueprint, request, jsonify
from datetime import datetime
from firebase_admin import storage 

upload_bp = Blueprint('upload_bp', __name__)

def get_bucket():
    return storage.bucket()

@upload_bp.route('/upload-image', methods=['POST'])
def upload_image():
    try:
        image_data = request.get_data()
        if not image_data:
            return jsonify({"error": "No image data received"}), 400

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"image_{timestamp}.jpg"

        # Firebase Storage 업로드
        bucket = get_bucket()
        blob = bucket.blob(f"uploads/{filename}")
        blob.upload_from_string(image_data, content_type='image/jpeg')
        blob.make_public()

        image_url = blob.public_url
        print(f"✅ 업로드 완료: {image_url}")

        return jsonify({"result": "ok", "url": image_url})

    except Exception as e:
        print("❌ 오류 발생:", str(e))
        return jsonify({"error": str(e)}), 500
