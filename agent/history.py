from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import asyncio
import logging
from pydantic import BaseModel
from typing import Dict, Optional
from os import getenv
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables

HISTORY_DB = "ChatHistory"
HISTORY_COLLECTION = "ChatHistory"
MONGO_USER = getenv("MONGO_USER")
MONGO_PASSWORD = getenv("MONGO_PASSWORD")
CONNECTION_STRING = getenv("CONNECTION_STRING")
URI = f"mongodb+srv://{MONGO_USER}:{MONGO_PASSWORD}@{CONNECTION_STRING}"

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
def serialize_mongo_doc_sync(doc):
    return serialize_mongo_doc(doc)
class History:
    def __init__(self, uri: str = URI):
        try:
            self.uri=uri
            self.HISTORY_DB = HISTORY_DB
            self.HISTORY_COLLECTION = HISTORY_COLLECTION
            self.client = None
            self.db = None
            self.collection = None
            logger.info("MongoDB (Motor) connection established successfully.")
            self.ensure_indexes()
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB connection: {str(e)}")
            self.client = None  # Mark unusable safely

    async def get_collection(self):
        if self.client is None:
            self.client = AsyncIOMotorClient(self.uri)
        if self.collection is None:
            self.db = self.client[HISTORY_DB]
            self.collection = self.db[HISTORY_COLLECTION]
        
        return self.collection

    async def close(self):
        if self.client:
            self.client.close()
            self.client = None

    async def ensure_indexes(self):
        collection = await self.get_collection()
        await collection.create_index([("user_id", 1), ("timestamp", -1)])
        self.close()

    async def retrieve_history(self, user_id: str, filter: Dict = {}, look_back: int = 10) -> APIResponse:
        if not user_id:
            return APIResponse(status="error", error="user_id cannot be empty")
        if look_back <= 0:
            return APIResponse(status="error", error="look_back must be a positive integer")

        try:
            query_filter = {"user_id": user_id}
            query_filter.update(filter)
            
            collection = await self.ensure_indexes()
            projection = {"user_query": 1, "response": 1, "_id": 0, "created_at":0, "updated_at":0}
            cursor = collection.find(query_filter, projection).sort("timestamp", -1).limit(look_back)
            history_list = await cursor.to_list(length=look_back)

            # logger.info(f"History raw: {history_list}")
            
            loop = asyncio.get_running_loop()
            history_list = await asyncio.gather(*[
                loop.run_in_executor(None, serialize_mongo_doc_sync, doc)
                for doc in history_list
            ])

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

            collection = await self.get_collection()
            await collection.insert_one(response_data)

            logger.info(f"History saved successfully for user {user_id}")

            return APIResponse(status="success", data={"message": "History saved successfully"})

        except Exception as e:
            logger.error(f"Error saving history for user {user_id}: {str(e)}")
            return APIResponse(status="error", error="Failed to save chat history")
