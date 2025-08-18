from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
import uuid
import json

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

# Initialize processor (consider using dependency injection)
processor = InputProcessor()

@router.post("/process", response_model=VoiceProcessResponse)
async def process_voice_input(
    request: VoiceProcessRequest,
    background_tasks: BackgroundTasks
):
    """Main voice processing endpoint."""
    request_id = str(uuid.uuid4())
    start_time = datetime.now()
    
    logger.info(f"Request {request_id}: Processing input from user {request.user_id}")
    
    try:
        # Convert to dict for processing
        request_dict = {
            "text": request.text,
            "audio_data": request.audio_data,
            "user_id": request.user_id,
            "timestamp": request.timestamp or datetime.now().isoformat(),
            "input_method": request.input_method,
            "browser_preview": request.browser_preview,
            "request_id": request_id,
            "explicit_complete_memory": True
        }

        logger.info(f"Request {request_id}: Received input - {json.dumps(request_dict, indent=2)}")
        
        # Process the input
        result = await processor.process_request(request_dict)
        
        # Access the nested structure correctly
        response_data = result.get('result', {}).get('final_response', {}).get('response_text', '')
        
        # Calculate total processing time
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        return JSONResponse(
            status_code=200, 
            content={
                "result": response_data, 
                'processing_time_ms': processing_time, 
                'request_id': request_id
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Request {request_id}: Unexpected error - {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Internal server error",
                "message": str(e),
                "request_id": request_id
            }
        )


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