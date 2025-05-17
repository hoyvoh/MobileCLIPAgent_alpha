import os 
import sys
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware  
from typing import Optional
from agent import Agent 
import datetime 
from fastapi.exceptions import HTTPException
import logging

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI() 
agent = Agent() 


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/v1/agent/get_text_response/", summary="Get response from agent")
async def get_response(
    conversation_id: str = Form(...),
    user_id: str = Form(...),
    text: str = Form(...),
):

    print(f"Received request with conversation_id: {conversation_id}, user_id: {user_id}, text: {text}")
    try:
        timestamp = datetime.datetime.now().isoformat()
        input_data = {
            "query": text,
        }

        response = await agent.get_response(
            user_id=user_id,
            input_data=input_data
        )
        
        logger.info(f"Response from agent: {response}")

        response_time = datetime.datetime.now()
        response["latency"] = (response_time - datetime.datetime.fromisoformat(timestamp)).total_seconds()
        return_data = {
            "action": "get_response",
            "status": "success",
            "response": response,
        }

        return return_data

    except ValueError as ve:
        logger.error(f"Invalid input data: {str(ve)}")
        raise HTTPException(status_code=400, detail={
            "action": "get_response",
            "status": "error",
            "error": "Invalid input data",
            "message": str(ve)
        })
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail={
            "action": "get_response",
            "status": "error",
            "error": "Internal server error",
            "message": "An unexpected error occurred"
        })
    
@app.post("/api/v1/agent/get_image_response/", summary="Get response from agent")
async def get_response(
    conversation_id: str = Form(...),
    user_id: str = Form(...),
    text: str = Form(None),
    image: Optional[UploadFile] = File(...),
):

    print(f"Received request with conversation_id: {conversation_id}, user_id: {user_id}, text: {text}")
    try:
        timestamp = datetime.datetime.now().isoformat()
        input_data = {
            "query": text,
            "image": image,
        }

        response = await agent.get_response(
            user_id=user_id,
            input_data=input_data
        )
        
        logger.info(f"Response from agent: {response}")

        response_time = datetime.datetime.now()
        response["latency"] = (response_time - datetime.datetime.fromisoformat(timestamp)).total_seconds()
        return_data = {
            "action": "get_response",
            "status": "success",
            "response": response,
        }

        return return_data

    except ValueError as ve:
        logger.error(f"Invalid input data: {str(ve)}")
        raise HTTPException(status_code=400, detail={
            "action": "get_response",
            "status": "error",
            "error": "Invalid input data",
            "message": str(ve)
        })
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail={
            "action": "get_response",
            "status": "error",
            "error": "Internal server error",
            "message": "An unexpected error occurred"
        })