from fastapi import APIRouter, HTTPException, BackgroundTasks, File, UploadFile, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
import uuid
import base64
import json
import os

#from api.models import VoiceProcessRequest, VoiceProcessResponse
from core.inputProcessor import InputProcessor
from utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["voice"])

# Request/Response Models
class VoiceProcessRequest(BaseModel):
    text: Optional[str] = None
    audio_data: Optional[str] = Field(None, description="Base64 encoded audio data")
    user_id: str
    timestamp: Optional[str] = None
    input_method: str = "text"  # "text" or "voice"
    browser_preview: Optional[str] = None  # For debugging/comparison

class VoiceProcessResponse(BaseModel):
    success: bool
    result: Dict[str, Any]
    timestamp: str
    processing_time_ms: int
    request_id: str

# Ensure uploads folder exists
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# Initialize processor (consider using dependency injection)
processor = InputProcessor()

@router.post("/process", response_model=VoiceProcessResponse)
async def process_voice_input(
    browser_transcript: str = Form(..., description="Transcript from browser speech recognition"),
    user_id: str = Form(default="anonymous", description="User identifier"),
    timestamp: Optional[str] = Form(default=None, description="Request timestamp"),
    input_method: str = Form(default="voice", description="Input method"),
    browser_preview: str = Form(default="false", description="Whether this is a preview"),
    
    # Audio file (optional - will be None if no audio sent)
    audio: Optional[UploadFile] = File(None, description="Audio file"),
    
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """Main voice processing endpoint - now handles FormData."""
    request_id = str(uuid.uuid4())
    start_time = datetime.now()

    logger.info(f"Request {request_id}: Processing FormData from user {user_id}")
    try:
        # Handle audio data
        audio_data = None
        if audio is not None:
            # Read the uploaded audio file
            audio_content = await audio.read()

            # Save to temp file if needed
            temp_file_path = f"uploads/temp_audio_{request_id}.webm"
            with open(temp_file_path, "wb") as f:
                f.write(audio_content)

            logger.info(f"Request {request_id}: Audio saved to {temp_file_path}")
            audio_data = temp_file_path
        else:
            logger.info(f"Request {request_id}: No audio file provided")
        
        # Convert form data to your existing request_dict format
        request_dict = {
            "text": "",
            "audio_data": audio_data,  # Will be None if no audio
            "browser_transcript": browser_transcript,
            "user_id": user_id,
            "timestamp": timestamp or datetime.now().isoformat(),
            "input_method": input_method,
            "browser_preview": browser_preview.lower() == "true",  # Convert string to boolean
            "request_id": request_id,
            "explicit_complete_memory": True
        }
        
        # Process the input
        result = await processor.process_request(request_dict)

        # Clean up temp file if it exists
        if audio_data and os.path.exists(audio_data):
            background_tasks.add_task(os.remove, audio_data)
        
        # Get the transcribed text from the processed input
        transcribed_text = ""
        if result:
            # First check if there's an error
            if not result.get('success', True):
                logger.error(f"Request {request_id}: Processing failed: {result.get('error')}")
                return JSONResponse(
                    status_code=500,
                    content={
                        "success": False,
                        "error": result.get('error', 'Unknown error'),
                        "request_id": request_id
                    }
                )
            
            # Access the nested structure correctly
            response_data = result.get('result', {}).get('final_response', {}).get('response_text', '')
            # If successful, extract the transcribed text
            if result.get('text', ''):
                transcribed_text = result["text"]
            else:
                # Fallback to browser transcript if no transcription from backend
                transcribed_text = browser_transcript
                logger.info(f"Request {request_id}: Using browser transcript as fallback")
        else:
            # If no result at all, use the browser transcript
            transcribed_text = browser_transcript
            logger.info(f"Request {request_id}: No result from processor, using browser transcript")
        
        # Calculate total processing time
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        logger.info(f"Response with transcribed text: {transcribed_text[:50]}...")

        # Return the transcribed text to the client
        return JSONResponse(
            status_code=200, 
            content={
                "success": True,
                "result": response_data,
                "transcribed_text": transcribed_text,
                "processing_time_ms": processing_time, 
                "request_id": request_id
            }
        )
        # return VoiceProcessResponse(
        #     success=True,
        #     transcribed_text=request_dict["text"],  # or your improved transcript
        #     response="Successfully processed your request",  # your actual response
        #     request_id=request_id,
        #     processing_time=(datetime.now() - start_time).total_seconds()
        # )
        
    except Exception as e:
        logger.error(f"Request {request_id}: Error processing - {str(e)}")
        return VoiceProcessResponse(
            success=False,
            error=str(e),
            request_id=request_id,
            processing_time=(datetime.now() - start_time).total_seconds()
        )



@router.post("/upload")
async def upload_audio(file: UploadFile = File(None)):
    logger.info(f"entered the function")
    try:
        # Case 1: If file comes from form-data (frontend or Postman)
        if file:
            filename = f"audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}{os.path.splitext(file.filename)[1]}"
            filepath = os.path.join(UPLOAD_FOLDER, filename)

            with open(filepath, "wb") as f:
                f.write(await file.read())

            return JSONResponse({"message": "File saved", "path": filepath})

        # Case 2: If base64 string is sent in JSON (raw body)
        # elif audioBase64:
        #     audio_bytes = base64.b64decode(audioBase64)
        #     filename = f"audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.webm"
        #     filepath = os.path.join(UPLOAD_FOLDER, filename)

        #     with open(filepath, "wb") as f:
        #         f.write(audio_bytes)

        #     return JSONResponse({"message": "File saved", "path": filepath})

        else:
            return JSONResponse({"error": "No audio found in request"}, status_code=400)

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)




# @router.post("/process", response_model=VoiceProcessResponse)
# async def process_voice_input(
#     request: VoiceProcessRequest,
#     background_tasks: BackgroundTasks
# ):
#     """Main voice processing endpoint."""
#     request_id = str(uuid.uuid4())
#     start_time = datetime.now()
    
#     logger.info(f"Request {request_id}: Processing input from user {request.user_id}")
    
#     try:
#         # Convert to dict for processing
#         request_dict = {
#             "text": request.text,
#             "audio_data": request.audio_data,
#             "user_id": request.user_id,
#             "timestamp": request.timestamp or datetime.now().isoformat(),
#             "input_method": request.input_method,
#             "browser_preview": request.browser_preview,
#             "request_id": request_id,
#             "explicit_complete_memory": True
#         }

#         logger.info(f"Request {request_id}: Received input - {json.dumps(request_dict, indent=2)}")
        
#         # Process the input
#         result = await processor.process_request(request_dict)
        
#         # Access the nested structure correctly
#         response_data = result.get('result', {}).get('final_response', {}).get('response_text', '')
        
#         # Calculate total processing time
#         processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
#         return JSONResponse(
#             status_code=200, 
#             content={
#                 "result": response_data, 
#                 'processing_time_ms': processing_time, 
#                 'request_id': request_id
#             }
#         )
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Request {request_id}: Unexpected error - {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail={
#                 "error": "Internal server error",
#                 "message": str(e),
#                 "request_id": request_id
#             }
#         )


# # # api/routes/voice_routes.py - Voice processing endpoints
# # from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
# # from pydantic import BaseModel, Field
# # from typing import Optional, Dict, Any
# # import base64
# # import logging

# # # Import orchestrator
# # from orchestration.orchestrator import Orchestrator

# # logger = logging.getLogger(__name__)

# # # Create router
# # router = APIRouter(prefix="/api/voice", tags=["voice"])

# # # Request/Response models
# # class VoiceProcessRequest(BaseModel):
# #     """Generic voice processing request"""
# #     audio_data: Optional[str] = Field(None, description="Base64 encoded audio data")
# #     text: Optional[str] = Field("", description="Text input if no audio")
# #     metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

# # class VoiceProcessResponse(BaseModel):
# #     """Generic voice processing response"""
# #     response: str
# #     voice_data: Optional[Dict[str, Any]] = None
# #     insights: Optional[list] = None
# #     memory_stored: Optional[bool] = None
# #     memories_retrieved: Optional[list] = None
# #     error: Optional[str] = None

# # # Dependency to get orchestrator instance
# # def get_orchestrator() -> Orchestrator:
# #     """Get the orchestrator instance from app state"""
# #     from main import app
# #     if not hasattr(app.state, 'orchestrator'):
# #         raise HTTPException(status_code=503, detail="Orchestrator not initialized")
# #     return app.state.orchestrator

# # @router.post("/process", response_model=VoiceProcessResponse)
# # async def process_voice(
# #     request: VoiceProcessRequest,
# #     orchestrator: Orchestrator = Depends(get_orchestrator)
# # ):
# #     """
# #     Process voice input through the orchestrator
    
# #     This endpoint simply forwards the request to the orchestrator
# #     and returns its response.
# #     """
# #     try:
# #         # Build orchestrator input
# #         orchestrator_input = {
# #             "text": request.text or "",
# #             "audio_data": request.audio_data,
# #             "metadata": request.metadata
# #         }
        
# #         # Process through orchestrator
# #         result = await orchestrator.process(orchestrator_input)
        
# #         # Return orchestrator response directly
# #         return VoiceProcessResponse(
# #             response=result.get("response", ""),
# #             voice_data=result.get("voice_data"),
# #             insights=result.get("insights"),
# #             memory_stored=result.get("memory_stored"),
# #             memories_retrieved=result.get("memories_retrieved"),
# #             error=result.get("error")
# #         )
        
# #     except Exception as e:
# #         logger.error(f"Voice processing error: {e}")
# #         raise HTTPException(status_code=500, detail=str(e))

# # # @router.post("/upload")
# # # async def upload_voice_file(
# # #     file: UploadFile = File(...),
# # #     metadata: Optional[str] = None,
# # #     orchestrator: Orchestrator = Depends(get_orchestrator)
# # # ):
# # #     """
# # #     Upload a voice file for processing
    
# # #     Converts the file to base64 and forwards to orchestrator.
# # #     """
# # #     try:
# # #         # Read and encode file
# # #         audio_bytes = await file.read()
# # #         audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
        
# # #         # Parse metadata if provided
# # #         import json
# # #         parsed_metadata = {}
# # #         if metadata:
# # #             try:
# # #                 parsed_metadata = json.loads(metadata)
# # #             except:
# # #                 pass
        
# # #         # Add file info to metadata
# # #         parsed_metadata["filename"] = file.filename
# # #         parsed_metadata["content_type"] = file.content_type
        
# # #         # Build orchestrator input
# # #         orchestrator_input = {
# # #             "text": "",
# # #             "audio_data": audio_base64,
# # #             "metadata": parsed_metadata
# # #         }
        
# # #         # Process through orchestrator
# # #         result = await orchestrator.process(orchestrator_input)
        
# # #         # Return result
# # #         return {
# # #             "response": result.get("response", ""),
# # #             "voice_data": result.get("voice_data"),
# # #             "insights": result.get("insights"),
# # #             "memory_stored": result.get("memory_stored"),
# # #             "memories_retrieved": result.get("memories_retrieved"),
# # #             "error": result.get("error")
# # #         }
        
# # #     except Exception as e:
# # #         logger.error(f"File upload error: {e}")
# # #         raise HTTPException(status_code=500, detail=str(e))

# # # @router.get("/health")
# # # async def voice_health_check(orchestrator: Orchestrator = Depends(get_orchestrator)):
# # #     """Check voice service health"""
# # #     try:
# # #         # Get agent pool stats
# # #         pool_stats = orchestrator.agent_pool.get_pool_stats()
        
# # #         return {
# # #             "status": "healthy",
# # #             "voice_agent_stats": pool_stats.get("voice", {}),
# # #         }
# # #     except Exception as e:
# # #         return {
# # #             "status": "unhealthy",
# # #             "error": str(e)
# # #         }

# from flask import Flask, request, jsonify
# from flask_cors import CORS
# import base64
# from orchestrator_single import process_voice_sync
# import os
# from dotenv import load_dotenv

# load_dotenv()

# app = Flask(__name__)
# CORS(app)

# # Create router
# router = APIRouter(prefix="/api/voice", tags=["voice"])

# @app.route('/')
# def home():
#     return jsonify({
#         "message": "Life Witness Agent API",
#         "version": "1.0.0",
#         "endpoints": {
#             "/api/voice/process": "POST - Process voice input",
#             "/api/text/process": "POST - Process text input (for testing)",
#             "/api/health": "GET - Health check"
#         }
#     })

# @app.route('/api/voice/process', methods=['POST'])
# def process_voice():
#     """Process voice input"""
#     try:
#         data = request.json
#         audio_base64 = data.get('audio')
        
#         if not audio_base64:
#             return jsonify({"error": "No audio data provided"}), 400
        
#         # Decode base64 audio
#         audio_bytes = base64.b64decode(audio_base64)
        
#         # Process through orchestrator
#         result = process_voice_sync(audio_data=audio_bytes)
        
#         return jsonify(result)
        
#     except Exception as e:
#         return jsonify({"error": str(e)}), 500

# @app.route('/api/text/process', methods=['POST'])
# def process_text():
#     """Process text input (for testing without audio)"""
#     try:
#         data = request.json
#         text = data.get('text', '')
        
#         if not text:
#             return jsonify({"error": "No text provided"}), 400
        
#         # Process through orchestrator
#         result = process_voice_sync(test_text=text)
        
#         return jsonify(result)
        
#     except Exception as e:
#         return jsonify({"error": str(e)}), 500

# @app.route('/api/health', methods=['GET'])
# def health():
#     """Health check"""
#     return jsonify({
#         "status": "healthy",
#         "service": "life-witness-agent"
#     })

# if __name__ == '__main__':
#     port = int(os.getenv('PORT', 8000))
#     app.run(host='0.0.0.0', port=port, debug=True)
