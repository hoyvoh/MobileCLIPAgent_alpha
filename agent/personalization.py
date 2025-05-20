import redis.asyncio as redis
from openai import AsyncOpenAI, APIError, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential
from pydantic import BaseModel, Field
from typing import Optional, Dict, List
from aiologger import Logger
from aiologger.formatters.json import JsonFormatter
import hashlib
import asyncio
from os import getenv
from asyncio_throttle import Throttler

# Configure async logging
logger = Logger.with_default_handlers(formatter=JsonFormatter(), level="INFO")

class APIResponse(BaseModel):
    status: str
    error: Optional[str] = None
    data: Optional[Dict] = None

class UserSummaryInput(BaseModel):
    user_id: str = Field(..., description="ID of the user")
    raw_input: str = Field(..., description="Raw input for summarization")

class Personalization:
    def __init__(self, redis_url: str = getenv("REDIS_URL", "redis://localhost:6379"), 
                 openai_api_key: str = getenv("OPENAI_API_KEY"), 
                 summarizer=None):
        self.redis = redis.Redis.from_url(redis_url, decode_responses=True, max_connections=100)
        self.summarizer = AsyncOpenAI(api_key=openai_api_key) if summarizer is None else summarizer
        self.throttler = Throttler(rate_limit=10, period=1.0)  # 10 requests/second
        self._closed = False
        asyncio.create_task(self._log_init())

    async def _log_init(self):
        await logger.info({"message": "Personalization initialized", "redis_url": self.redis.connection_pool.connection_kwargs.get("host")})

    async def close(self):
        if not self._closed:
            await self.redis.close()
            if hasattr(self.summarizer, "close"):
                await self.summarizer.close()
            await logger.info({"message": "Personalization resources closed"})
            self._closed = True

    async def invalidate_cache(self, user_id: str, exclude: Optional[str] = None):
        try:
            keys = await self.redis.keys(f"summary:{user_id}:*")
            if exclude:
                keys = [k for k in keys if k != exclude]
            if keys:
                await self.redis.delete(*keys)
                await logger.info({
                    "message": "Cache invalidated",
                    "user_id": user_id,
                    "keys_deleted": len(keys)
                })
        except redis.RedisError as e:
            await logger.error({"message": "Cache invalidation failed", "error": str(e), "user_id": user_id})

    async def retrieve_user_summary(self, user_id: str) -> APIResponse:
        try:
            UserSummaryInput(user_id=user_id, raw_input="")  # Validate user_id
            cache_key = f"summary:{user_id}"
            summary = await self.redis.get(cache_key)
            if summary:
                await logger.info({
                    "message": "Summary retrieved from cache",
                    "user_id": user_id,
                    "cache_key": cache_key
                })
                return APIResponse(status="success", data={"summary": summary})
            return APIResponse(status="not_found", data={})
        except redis.RedisError as e:
            await logger.warning({
                "message": "Redis error, falling back to empty summary",
                "error": str(e),
                "user_id": user_id
            })
            return APIResponse(status="not_found", data={})
        except Exception as e:
            await logger.error({
                "message": "Unexpected error retrieving summary",
                "error": str(e),
                "user_id": user_id
            })
            return APIResponse(status="error", error="Failed to retrieve summary")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def summarize_input(self, raw_input: str) -> Optional[str]:
        try:
            if not self.summarizer:
                raise ValueError("Summarizer not provided")
            async with self.throttler:
                prompt = (
                    "Tóm tắt thông tin người dùng (tên, tuổi, nghề nghiệp, sở thích mua sắm, tone giọng phù hợp) "
                    "từ input sau, tối đa 100 từ:\n\n"
                    f"Input: {raw_input}"
                )
                response = self.summarizer.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Bạn là nhà phân tích tâm lý khách hàng."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=150
                )
                summary = response.choices[0].message.content.strip()
                await logger.info({"message": "Summarization completed", "input_length": len(raw_input)})
                return summary
        except RateLimitError:
            await logger.error({"message": "OpenAI rate limit exceeded"})
            return None
        except APIError as e:
            await logger.error({"message": "OpenAI API error", "error": str(e)})
            return None
        except Exception as e:
            await logger.error({"message": "Summarization error", "error": str(e)})
            return None

    async def create_or_update_summary(self, user_id: str, raw_input) -> APIResponse:
        try:
            raw_input = str(f"User query: {raw_input.get("user_query")}. Response:{raw_input.get("response")}")
            validated = UserSummaryInput(user_id=user_id, raw_input=raw_input)
            cache_key = f"summary:{user_id}:{hashlib.sha256(raw_input.encode()).hexdigest()}"
            
            # Check cache
            summary = await self.redis.get(cache_key)
            if summary:
                await logger.info({
                    "message": "Summary retrieved from cache",
                    "user_id": user_id,
                    "cache_key": cache_key
                })
                return APIResponse(status="success", data={"summary": summary})

            # Summarize and cache
            summary_text = await self.summarize_input(validated.raw_input)
            if not summary_text:
                summary_text = "Default summary due to summarization failure"
                await logger.warning({
                    "message": "Using default summary due to summarization failure",
                    "user_id": user_id
                })

            await self.redis.setex(cache_key, 3600*24, summary_text)  # Cache for 24 hours
            await self.invalidate_cache(user_id, exclude=cache_key)
            await logger.info({
                "message": "Summary created/updated",
                "user_id": user_id,
                "cache_key": cache_key
            })
            return APIResponse(status="success", data={"summary": summary_text})
        except redis.RedisError as e:
            await logger.error({
                "message": "Redis error during summary creation",
                "error": str(e),
                "user_id": user_id
            })
            # Fallback to direct return without caching
            summary_text = await self.summarize_input(raw_input) or "Default summary due to summarization failure"
            return APIResponse(status="success", data={"summary": summary_text})
        except Exception as e:
            await logger.error({
                "message": "Unexpected error during summary creation",
                "error": str(e),
                "user_id": user_id
            })
            return APIResponse(status="error", error="Failed to create or update summary")

    async def summarize_batch(self, inputs: List[Dict[str, str]]) -> List[APIResponse]:
        results = []
        for input_data in inputs:
            result = await self.create_or_update_summary(input_data["user_id"], input_data["raw_input"])
            results.append(result)
        return results