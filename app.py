from flask import Flask
from config import Config
from extensions import mongo
from routes.signup.user_routes import user_bp
from routes.chat.chat_meal import chat_meal_bp
from routes.chat.chat_water import record_water_bp
from routes.chat.chat_sleep import record_sleep_bp
from routes.chat.chat_news import news_bp
from routes.upload.upload import upload_bp
from extensions import mongo
import firebase_admin
from firebase_admin import credentials, storage

cred = credentials.Certificate("firebase-key.json")
firebase_admin.initialize_app(cred, {
    'storageBucket': 'shim-ae600.firebasestorage.app'
})

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    mongo.init_app(app)
    app.register_blueprint(user_bp)
    app.register_blueprint(chat_meal_bp)
    app.register_blueprint(record_water_bp)
    app.register_blueprint(record_sleep_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(upload_bp)
    return app

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        print("[DEBUG] mongo 객체:", mongo)
        print("[DEBUG] mongo.db 객체:", mongo.db)
    app.run(host='0.0.0.0', port=5000, debug=True)

print("[DEBUG] MONGO_URI 값:", Config.MONGO_URI)

