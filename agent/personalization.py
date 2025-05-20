import redis.asyncio as redis
from pydantic import BaseModel
from typing import Optional, Dict
import logging
from datetime import datetime
from os import getenv

'''
Class Personalization
- Khởi tạo:
+ Client: Mongo Client
+ DB: MongoClient[DBName]
+ collection: db[collection name]
+ summarizer: chatbot
+ personalization type: UserProfile
{
"user_id":
"personalizations":{
     "personal_info":[],
     "summary":[]
  }
}
Methods:
- Summarize_input()
- create_user_summary (): summarize + create new record
- retrieve_user_summary (): search for user_record by id
- update_user_summary (): search for user record by id + update summary + update record 
Fails:
- return status and traceback
'''

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PERSONALIZATION_DB = "ChatHistory"
PERSONALIZATION_COLLECTION = "Personalization"

class APIResponse(BaseModel):
    status: str
    error: Optional[str] = None
    data: Optional[Dict] = None

class Personalization:
    def __init__(self, redis_url: str = getenv("REDIS_URL", "redis://localhost:6379"), summarizer=None):
        self.redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self.summarizer = summarizer

    async def retrieve_user_summary(self, user_id: str) -> APIResponse:
        try:
            summary = await self.redis.get(user_id)
            if summary:
                return APIResponse(status="success", data={"summary": summary})
            return APIResponse(status="not_found", data={})
        except Exception as e:
            logger.error(f"Error retrieving summary: {e}")
            return APIResponse(status="error", error="Failed to retrieve summary")

    async def create_or_update_summary(self, user_id: str, raw_input: str) -> APIResponse:
        try:
            if not raw_input or not user_id:
                return APIResponse(status="error", error="user_id and input are required")

            summary_text = await self.summarize_input(raw_input)
            if not summary_text:
                return APIResponse(status="error", error="Summarizer failed")

            await self.redis.set(user_id, summary_text)
            return APIResponse(status="success", data={"summary": summary_text})
        except Exception as e:
            logger.error(f"Error saving summary: {e}")
            return APIResponse(status="error", error="Failed to save summary")

    async def summarize_input(self, raw_input: str) -> Optional[str]:
        try:
            if not self.summarizer:
                raise ValueError("Summarizer not provided")

            prompt = (
                "Đọc nội dung này và tóm tắt các thông tin về người dùng nếu có, về tên, tuổi, nghề nghiệp, gia đình, con cái, các mối quan tâm, hành vi mua sắm như thích những vật phẩm gì, có khả năng sẽ mua gì, nên sử dụng tone giọng như thế nào để tiếp cận.\n\n"
                f"Input: {raw_input}"
            )

            response = self.summarizer.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Công việc của bạn là một nhà phân tích tâm lý khách hàng."},
                    {"role": "user", "content": prompt}
                ]
            )

            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Summarization error: {e}")
            return None
