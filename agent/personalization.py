from datetime import datetime
from typing import Dict, List, Optional
import logging
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from dotenv import load_dotenv
from os import getenv

load_dotenv(override=True)

MONGO_USER = getenv("MONGO_USER")
MONGO_PASSWORD = getenv("MONGO_PASSWORD")
CONNECTION_STRING = getenv("CONNECTION_STRING")
URI = f"mongodb+srv://{MONGO_USER}:{MONGO_PASSWORD}@{CONNECTION_STRING}"


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

class UserProfile(BaseModel):
    personal_info: List[str]
    preferences: List[str]

class APIResponse(BaseModel):
    status: str
    error: Optional[str] = None
    data: Optional[Dict] = None

def serialize_mongo_doc(doc):
    if isinstance(doc, dict):
        doc = dict(doc)
        if "_id" in doc and isinstance(doc["_id"], ObjectId):
            doc["_id"] = str(doc["_id"])
    return doc

class Personalization:
    def __init__(self, uri=URI, summarizer=None):
        try:
            self.PERSONALIZATION_DB = PERSONALIZATION_DB
            self.PERSONALIZATION_COLLECTION = PERSONALIZATION_COLLECTION
            self.client = client
            self.db = self.client[self.PERSONALIZATION_DB]
            self.collection = self.db[self.PERSONALIZATION_COLLECTION]
            logger.info("MongoDB (Motor) connection established successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB connection: {str(e)}")
            self.client = None
        self.summarizer = summarizer
        self.personalization_type = UserProfile
        if not self.summarizer:
            logger.warning("No summarizer provided. Summarization disabled.")

    async def retrieve_user_summary(self, user_id: str) -> APIResponse:
        if not user_id:
            return APIResponse(status="error", error="user_id cannot be empty")

        try:
            document = await self.collection.find_one({"user_id": user_id})
            if not document:
                logger.info(f"No summary found for user {user_id}")
                return APIResponse(status="not_found", data={})

            logger.info(f"Summary retrieved successfully for user {user_id}")
            return APIResponse(status="success", data=serialize_mongo_doc(document))

        except Exception as e:
            logger.error(f"Error retrieving summary for user {user_id}: {str(e)}")
            return APIResponse(status="error", error="Failed to retrieve user summary")

    async def create_user_summary(self, user_id: str, raw_input: str) -> APIResponse:
        if not user_id:
            return APIResponse(status="error", error="user_id cannot be empty")
        if not raw_input:
            return APIResponse(status="error", error="raw_input cannot be empty")

        try:
            existing = await self.collection.find_one({"user_id": user_id})
            if existing:
                return APIResponse(status="error", error=f"User {user_id} already has a summary")

            final_summary = await self.summarize_input(raw_input=raw_input, current_summary="")

            document = {
                "user_id": user_id,
                "summary": final_summary,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }

            await self.collection.insert_one(document)
            logger.info(f"Summary created successfully for user {user_id}")
            return APIResponse(status="success", data={"user_id": user_id})

        except Exception as e:
            logger.error(f"Error creating summary for user {user_id}: {str(e)}")
            return APIResponse(status="error", error="Failed to create user summary")

    async def update_user_summary(self, user_id: str, raw_input: Dict) -> APIResponse:
        if not user_id:
            return APIResponse(status="error", error="user_id cannot be empty")
        if not raw_input:
            return APIResponse(status="error", error="No raw_input provided")

        try:
            # Always retrieve first
            current_summary_response = await self.retrieve_user_summary(user_id)

            # If not found, create empty summary first
            if current_summary_response.status != "success" or not current_summary_response.data:
                logger.info(f"No existing summary for user {user_id}. Creating new summary.")
                create_result = await self.create_user_summary(user_id=user_id, raw_input=raw_input)
                if create_result.status != "success":
                    return create_result  # stop if create failed
                # Now fetch fresh after creation
                current_summary_response = await self.retrieve_user_summary(user_id)
                if current_summary_response.status != "success" or not current_summary_response.data:
                    return APIResponse(status="error", error="Failed to retrieve newly created summary")

            current_summary = current_summary_response.data.get("summary", {})
            # logger.info(f"Current summary for user {user_id}: {current_summary}")
            new_document = f"query: {raw_input.get('user_query', '')}\nContext: {raw_input.get('context', '')}\nResponse: {raw_input.get('response', '')}"
            # logger.info(f"New document for summarization: {new_document}")
            updated_summary = await self.summarize_input(raw_input=new_document, current_summary=current_summary)
            updated_summary["preferences"] = updated_summary.get("preferences", [])[:10]
            # logger.info(f"Updated summary for user {user_id}: {updated_summary}")

            await self.collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "summary": updated_summary,
                        "updated_at": datetime.now().isoformat()
                    }
                }
            )
            logger.info(f"Summary updated successfully for user {user_id}")
            return APIResponse(status="success", data={"user_id": user_id})

        except Exception as e:
            logger.error(f"Error updating summary for user {user_id}: {str(e)}")
            return APIResponse(status="error", error="Failed to update user summary")


    async def summarize_input(self, raw_input: str = '', current_summary: str = '') -> Dict:
        try:
            if not raw_input:
                raise ValueError("raw_input cannot be empty")
            if not self.summarizer:
                raise ValueError("Summarization unavailable")

            prompt = (
                "Summarize into two lists:\n"
                "- personal_info\n- preferences\n"
                f"Current summary: {current_summary}\n"
                f"Input: {raw_input}"
            )

            response = self.summarizer.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a summarization assistant."},
                    {"role": "user", "content": prompt}
                ],
                response_format=self.personalization_type
            )

            result = response.choices[0].message.parsed
            summary = result.model_dump()

            if not isinstance(summary, dict):
                raise ValueError("Invalid summarization output")

            return summary

        except Exception as e:
            logger.error(f"Error summarizing input: {str(e)}")
            raise


