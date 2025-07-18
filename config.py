import os
from dotenv import load_dotenv

load_dotenv()
print("[DEBUG] 실제 .env에서 불러온 MONGO_URI:", os.getenv("MONGO_URI"))  # 추가!

class Config:
    MONGO_URI = os.getenv("MONGO_URI")  # .env에 저장된 MongoDB URL
