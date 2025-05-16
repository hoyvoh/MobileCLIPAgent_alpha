from .history import History
from .personalization import Personalization
from .prompts import PROMPTS
import openai
import os 
from typing import Optional, Union
from pydantic import BaseModel, Field, StrictInt, StrictFloat, field_validator
from typing_extensions import Literal
from datetime import datetime
import requests
from motor.motor_asyncio import AsyncIOMotorClient
import dotenv
import boto3
import uuid
from botocore.exceptions import NoCredentialsError, ClientError
import logging
from fastapi import UploadFile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

dotenv.load_dotenv(override=True)

MONGO_USER = os.getenv("MONGO_USER")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
CONNECTION_STRING = os.getenv("CONNECTION_STRING")
URI = f"mongodb+srv://{MONGO_USER}:{MONGO_PASSWORD}@{CONNECTION_STRING}"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY
AWS_ACCESS_KEY=os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY=os.getenv("AWS_SECRET_KEY")

IMAGE_EMBEDDING_URL= os.getenv("IMAGE_EMBEDDING_URL", "http://text-embedding:3002/api/v1/embedding/")
TEXT_EMBEDDING_URL=os.getenv("TEXT_EMBEDDING_URL", "http://text-embedding:3002/api/v1/embedding/")

def upload_image_to_s3(
    image_file: Union[bytes, UploadFile],
    bucket_name="ezshop-bucket",
    folder="search-uploads",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name: str = "ap-southeast-2",
) -> str:
    # Nếu là UploadFile, đọc ra bytes
    if isinstance(image_file, UploadFile):
        image_bytes = image_file.file.read()  # sync read (nếu bên sync code)
    elif isinstance(image_file, bytes):
        image_bytes = image_file
    else:
        raise ValueError("Invalid image_file type. Must be bytes or UploadFile")

    # Xác định MIME và extension
    mime_type = 'application/octet-stream'
    file_ext = 'bin'

    if image_bytes[:4] == b'\x89PNG':
        mime_type = 'image/png'
        file_ext = 'png'
    elif image_bytes[:2] == b'\xff\xd8':
        mime_type = 'image/jpeg'
        file_ext = 'jpg'
    elif image_bytes[:6] in (b'GIF87a', b'GIF89a'):
        mime_type = 'image/gif'
        file_ext = 'gif'

    filename = f"{uuid.uuid4().hex}.{file_ext}"
    s3_key = f"{folder.rstrip('/')}/{filename}" if folder else filename

    s3_client = boto3.client(
        "s3",
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=region_name,
    )

    try:
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=image_bytes,
            ContentType=mime_type,
            ACL="public-read",
        )

        image_url = f"https://{bucket_name}.s3.{region_name}.amazonaws.com/{s3_key}"
        return image_url

    except NoCredentialsError:
        raise RuntimeError("AWS credentials not provided or invalid.")
    except ClientError as e:
        raise RuntimeError(f"Failed to upload image: {e.response['Error']['Message']}")


    except NoCredentialsError:
        raise RuntimeError("AWS credentials not provided or invalid.")
    except ClientError as e:
        raise RuntimeError(f"Failed to upload image: {e.response['Error']['Message']}")

class FilterResponse(BaseModel):
    rating_average: Optional[StrictFloat] = Field(None, description="Rating from 0 to 5")
    # price: Optional[List[StrictInt]] = None  
    review_count: Optional[StrictInt] = None
    category_level_1: Optional[str] = None

    @field_validator("rating_average")
    @classmethod
    def validate_rating_average(cls, value):
        if value is not None and not (0 <= value <= 5):
            raise ValueError("rating_average must be between 0 and 5")
        return value

class RouterResponse(BaseModel):
    needs_context: bool
    intent: str 
    query: Optional[str]
    collection: Literal["products", "policies_FAQ", "exists"]
    filter: Optional[FilterResponse] = None

class Agent:
    def __init__(self, model = "gpt-4o-mini-2024-07-18"):
        self.client = AsyncIOMotorClient(URI)
        self.chatbot = openai.OpenAI()
        self.model = model
        self.history = History(client=self.client) 
        self.personalization = Personalization(client=self.client, summarizer = self.chatbot)

    async def get_response(self, user_id, input_data):
        # print("Getting past conversations")
        past_convo_response = await self.history.retrieve_history(user_id=user_id, look_back=5)
        # logger.info(f"Past convo result before dump: {past_convo_response}")

        past_convo_result = past_convo_response.model_dump()
        # logger.info(f"Past convo result after dump: {past_convo_result}")

        if past_convo_result["status"] == "success" and past_convo_result.get("data"):
            chat_history = past_convo_result["data"].get("history", [])
            # logger.info(f"Chat history: {chat_history}")

        else:
            chat_history = ["No past conversations found."]
            logger.info("No past conversations found.")

        # print("Getting user summary")
        user_summary_response = await self.personalization.retrieve_user_summary(user_id)
        user_summary_result = user_summary_response.model_dump()
        if user_summary_result["status"] == "success" and user_summary_result.get("data"):
            user_summary = user_summary_result["data"].get("summary", {})
        else:
            user_summary = {"personal_info": [], "preferences": []}

        # print("Building router message")
        router_message = f"Past conversations: {chat_history}\nUser summary: {user_summary}\n"
        if input_data.get("query"):
            router_message += f"User query: {input_data['query']}"

        # print(router_message)

        image_url = ''

        if input_data.get("image"):

            image = input_data.get("image")

            if image:
                # Check nếu là UploadFile thì phải await, nếu là bytes thì dùng luôn
                if hasattr(image, "read") and callable(image.read):
                    image_bytes = await image.read()
                else:
                    image_bytes = image

                files = {
                    "image": ("image.jpg", image_bytes, "image/jpeg")
                }

                product_results = requests.post(IMAGE_EMBEDDING_URL, files=files).json()
                # print("Image search results:", product_results)

                if product_results.get("status") == "success":
                    product_results = product_results.get("data", {}).get("top_k_results", [])
                else:
                    product_results = []
                # print("Uploaded image to S3")
                image_url = upload_image_to_s3(image_bytes)
                # print("Image URL:", image_url)
                full_context_query = f"User's intent: {input_data.get("query", "Tìm sản phẩm bằng hình")}\nRelevant products:{str(product_results)}\nRecent Conversations:{chat_history}\nUser Summary:{user_summary}"
                # print("Full context query:", full_context_query)
        else:
            results = self.chatbot.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": PROMPTS.TEXT_PROMPT},
                    {"role": "user", "content": router_message}
                ],
                response_format=RouterResponse,
            ).choices[0].message.parsed
            full_context_query = f"User's intent: {results.intent}\nRecent Conversations:{chat_history}\nUser Summary:{user_summary}"
            if results.needs_context:
                logger.info("User needs context")
                body = {
                    'query':results.query,
                    'filter':results.filter.model_dump() if results.filter else {}
                }

                # logger.info(f"Body for text embedding: {body}")

                product_results = requests.post(TEXT_EMBEDDING_URL, json=body).json()
                # print("Product results:", product_results)
                if product_results.get("status") == "success":
                    product_results = product_results.get("data", {}).get("top_k_results", [])
                else:
                    product_results = []
                full_context_query += f"\nRelevant products:{str(product_results)}"

        # logger.info(f"Full context query: {full_context_query}")
        final_response = self.chatbot.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": PROMPTS.AGENT_PROMPT},
                {"role": "user", "content": full_context_query}
            ]
        ).choices[0].message.content

        response_data = {
            "user_id": user_id,
            "user_query": input_data.get("query", ""),
            "image": image_url,
            "response": final_response,
            "products": product_results, 
            "context": full_context_query,
            "timestamp": datetime.now().isoformat(),
        }
        # print("Response data:", response_data)

        # Always check save/update results
        save_history_response = await self.history.add_to_history(user_id, response_data)
        if save_history_response.status != "success":
            logger.warning(f"Failed to save history for user {user_id}: {save_history_response.error}")

        update_summary_response = await self.personalization.update_user_summary(user_id, response_data)
        if update_summary_response.status != "success":
            logger.warning(f"Failed to update user summary for user {user_id}: {update_summary_response.error}")
        
        response_data.pop("_id", None)

        return response_data


