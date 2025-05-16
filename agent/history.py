from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import logging
from pydantic import BaseModel
from typing import Dict, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables

HISTORY_DB = "ChatHistory"
HISTORY_COLLECTION = "ChatHistory"
'''
 class History:
Initialization
+ client: mongoDB client

Methods
+ retrieve history by user id, top 10, sort by time descending(user_id, ): search filer user id, top 10 sort by time
+ add to history (user_id, history_to_add): 
- insert to history with timestamp
'''

class APIResponse(BaseModel):
    status: str
    error: Optional[str] = None
    data: Optional[Dict] = None

logger = logging.getLogger("agent.history")
class APIResponse(BaseModel):
    status: str
    error: str = None
    data: dict = None

def serialize_mongo_doc(doc):
    """Helper to convert ObjectId to str inside a doc."""
    if isinstance(doc, dict):
        doc = dict(doc)
        if "_id" in doc and isinstance(doc["_id"], ObjectId):
            doc["_id"] = str(doc["_id"])
    return doc

class History:
    def __init__(self, client: AsyncIOMotorClient):
        try:
            self.HISTORY_DB = HISTORY_DB
            self.HISTORY_COLLECTION = HISTORY_COLLECTION
            self.client = client
            self.db = self.client[self.HISTORY_DB]
            self.collection = self.db[self.HISTORY_COLLECTION]
            logger.info("MongoDB (Motor) connection established successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB connection: {str(e)}")
            self.client = None  # Mark unusable safely

    async def retrieve_history(self, user_id: str, filter: Dict = {}, look_back: int = 10) -> APIResponse:
        if not user_id:
            return APIResponse(status="error", error="user_id cannot be empty")
        if look_back <= 0:
            return APIResponse(status="error", error="look_back must be a positive integer")

        try:
            query_filter = {"user_id": user_id}
            query_filter.update(filter)

            cursor = self.collection.find(query_filter).sort("timestamp", -1).limit(look_back)
            history_list = await cursor.to_list(length=look_back)
            # logger.info(f"History raw: {history_list}")
            history_list = [serialize_mongo_doc(h) for h in history_list]
            history_list = [
                [history["user_query"], history["response"]]
                for history in history_list
                if "user_query" in history and "response" in history
            ]

            logger.info(f"Retrieved {len(history_list)} history entries for user {user_id}")
            return APIResponse(status="success", data={"history": history_list})

        except Exception as e:
            logger.error(f"Error retrieving history for user {user_id}: {str(e)}")
            return APIResponse(status="error", error="Failed to retrieve chat history")

    async def add_to_history(self, user_id: str, response_data: Dict) -> APIResponse:
        if not user_id:
            return APIResponse(status="error", error="user_id cannot be empty")
        if not response_data or not isinstance(response_data, dict):
            return APIResponse(status="error", error="response_data must be a non-empty dictionary")

        try:
            required_fields = ["user_id", "user_query", "response", "context", "timestamp"]
            missing_fields = [f for f in required_fields if f not in response_data]
            if missing_fields:
                return APIResponse(status="error", error=f"Missing required fields: {', '.join(missing_fields)}")

            await self.collection.insert_one(response_data)
            logger.info(f"History saved successfully for user {user_id}")

            return APIResponse(status="success", data={"message": "History saved successfully"})

        except Exception as e:
            logger.error(f"Error saving history for user {user_id}: {str(e)}")
            return APIResponse(status="error", error="Failed to save chat history")
