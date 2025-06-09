from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import asyncio
import logging
from pydantic import BaseModel
from typing import Dict, Optional
from os import getenv
from dotenv import load_dotenv
from datetime import datetime
import time

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent.history")

HISTORY_DB = "ChatHistory"
HISTORY_COLLECTION = "ChatHistory"
MONGO_USER = getenv("MONGO_USER")
MONGO_PASSWORD = getenv("MONGO_PASSWORD")
CONNECTION_STRING = getenv("CONNECTION_STRING")
URI = f"mongodb+srv://{MONGO_USER}:{MONGO_PASSWORD}@{CONNECTION_STRING}"


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


def serialize_mongo_doc_sync(doc):
    return serialize_mongo_doc(doc)


class History:
    def __init__(self, uri: str = URI):
        try:
            self.uri = uri
            self.HISTORY_DB = HISTORY_DB
            self.HISTORY_COLLECTION = HISTORY_COLLECTION
            self.client = AsyncIOMotorClient(self.uri)
            self.db = self.client[self.HISTORY_DB]
            self.collection = self.db[self.HISTORY_COLLECTION]
            
            logger.info("MongoDB (Motor) client initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB connection: {str(e)}")
            self.client = None

    async def ensure_indexes(self):
        try:
            await self.collection.create_index([("user_id", 1), ("timestamp", -1)])
        except Exception as e:
            logger.warning(f"Index creation failed or already exists: {str(e)}")

    async def retrieve_history(self, user_id: str, filter: Dict = {}, look_back: int = 10) -> APIResponse:
        if not user_id:
            return APIResponse(status="error", error="user_id cannot be empty")
        if look_back <= 0:
            return APIResponse(status="error", error="look_back must be a positive integer")

        try:
            if self.collection is None:
                logger.error("MongoDB collection is not initialized")
                return APIResponse(status="error", error="Database connection not ready")

            query_filter = {"user_id": user_id}
            query_filter.update(filter)

            projection = {"user_query": 1, "response": 1, "_id": 0}
            start_time = time.time()
            cursor = self.collection.find(query_filter, projection).sort("timestamp", -1).limit(look_back)
            history_list = await cursor.to_list(length=look_back)
            query_time = time.time() - start_time
            logger.info(f"Query for user {user_id} took {query_time:.3f} seconds")

            if not history_list:
                logger.info(f"No history found for user {user_id}")
                return APIResponse(status="success", data={"history": []})
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
            required_fields = ["user_query", "response"]
            missing_fields = [f for f in required_fields if f not in response_data]
            if missing_fields:
                return APIResponse(status="error", error=f"Missing required fields: {', '.join(missing_fields)}")

            # Add metadata
            response_data.update({
                "user_id": user_id,
                "timestamp": datetime.now().isoformat(),
            })

            await self.collection.insert_one(response_data)

            logger.info(f"History saved successfully for user {user_id}")
            return APIResponse(status="success", data={"message": "History saved successfully"})

        except Exception as e:
            logger.error(f"Error saving history for user {user_id}: {str(e)}")
            return APIResponse(status="error", error="Failed to save chat history")
