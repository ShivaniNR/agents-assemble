from typing import Dict, Any, Optional
import logging
from datetime import datetime
import uuid
import google.generativeai as genai
from core.sessionManager import SessionManager
from services.storage_service import StorageService
from agents.planner_agent import PlannerAgent
from backend.agents.voice_agent import VoiceAgent  
from core.planExecutor import PlanExecutor
import os

logger = logging.getLogger(__name__)

class InputProcessor:
    """
    Main entry point for all user requests.
    Handles voice transcription, planning, and execution coordination.
    """

    def __init__(self, session_timeout_minutes: int = 30):

        #initialize ai client
        os.environ["GOOGLE_API_KEY"]= os.getenv("GOOGLE_API_KEY")
        self.gemini_model = genai.GenerativeModel('gemini-1.5-flash')

        # Initialize session management
        self.session_manager = SessionManager(session_timeout_minutes=session_timeout_minutes)
        self.storage_service = StorageService()

        # Initialize agents
        self.planner = PlannerAgent(self.session_manager, self.gemini_model)
        self.voice_agent = VoiceAgent(self.session_manager)
        self.executor = PlanExecutor(self.session_manager, self.storage_service)

        self.request_count = 0
        self.processing_history = []


    async def process_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main processing pipeline for all user inputs
        
        Enhanced main processing pipeline with session management
        
        Args:
            request_data: Dictionary containing:
                - text: Optional text input
                - audio_data: Optional base64 audio
                - audio_url: Optional audio file URL
                - user_id: User identifier
                - timestamp: Optional timestamp
                
        Returns:
            Processed response with result and metadata
        """

        request_id = str(uuid.uuid4())
        start_time = datetime.now()

        # Extract info from request
        user_id = request_data.get('user_id', 'unknown')

        #session_id creation
        session_id = None
        if 'session_id' not in request_data:
            initial_context = {
                "user_id": user_id,
                "created_from": "input_processor",
                "initial_input_type": "audio" if request_data.get("audio_data") else "text"
            }
            session_id = await self.session_manager.create_session(user_id, initial_context)

        
        logger.info(f"Processing request {request_id} for user {user_id}, session: {session_id}")

        try:
            #Step 1: Preprocess input (handle voice if present)
            processed_input = await self._preprocess_input(request_data, request_id, session_id)

            if processed_input.get("error"):
                return self._create_error_response(request_id, processed_input["error"])
            
            logger.info(f"Processed the input: {processed_input}")

            # Step 2: Create execution plan
            plan_result = await self._create_plan(processed_input, request_id)
            
            if plan_result.get("error"):
                return self._create_error_response(request_id, plan_result["error"])
            
            logger.info(f"Created the execution plan: {plan_result['data']}")

            plan = plan_result["data"]
            
            # Step 3: Execute the plan
            execution_result = await self._execute_plan(plan, processed_input, request_id)

            logger.info(f"Done with execution: {execution_result['success']}")
            
            # # Step 4: Track and return results
            processing_time = (datetime.now() - start_time).total_seconds()
            
            self._track_request(request_id, request_data, plan, execution_result, processing_time)
            
            return self._create_success_response(
                request_id, 
                execution_result, 
                plan, 
                processing_time
            )
            
        except Exception as e:
            logger.error(f"Request {request_id} failed: {str(e)}")
            return self._create_error_response(request_id, str(e))

    async def _preprocess_input(self, request_data: Dict[str, Any], request_id: str, session_id: str) -> Dict[str, Any]:
        """
        Preprocess input data - handle voice transcription if needed
        
        Args:
            request_data: Original request data
            request_id: Unique request identifier
            
        Returns:
            Processed input data with transcribed text
        """
        processed_data = request_data.copy()
        
        # Check if we have voice input that needs transcription
        has_audio = bool(request_data.get("audio_data") or request_data.get("audio_url"))
        has_text = bool(request_data.get("text", "").strip())

        #determin if the memory is complete or not
        explicit_memory_complete = request_data.get('explicit_complete_memory', False)
        
        if has_audio and not has_text:
            logger.info(f"Transcribing voice input for request {request_id}")
            
            try:
                # Use voice agent to transcribe TODO: Implement voice transcription logic
                transcription_result = await self.voice_agent.process({
                    "audio_data": request_data.get("audio_data"),
                    "audio_url": request_data.get("audio_url"),
                    "action": "transcribe",
                    "request_id": request_id
                })

                #mock response for testing
                # transcription_result = {'agent': 'VoiceAgent', 'status': 'success', 'timestamp': '2025-07-31T18:54:27.069902', 'data': {'transcript': 'Birch canoe, slid on the smooth planks.  Glue the sheet to the dark blue background.  it is easy to tell the depth of a well,  These days, a chicken leg is a rare dish.  Rice is often served in round bowls.  The juice of lemons makes fine punch.  The box was thrown beside the park truck.  The Hogs are fed, chopped corn and garbage.  Four hours of steady work faced us.  A large size and stockings is hard to sell.'}}

                logger.info(f"Transcribing voice done {transcription_result}")
                
                if transcription_result.get("status") == "success":
                    transcription_data = transcription_result.get("data", {})
                    processed_data["text"] = transcription_data.get("transcript", "")
                    # processed_data["voice_metadata"] = {
                    #     "confidence": transcription_data.get("confidence"),
                    #     "language": transcription_data.get("language"),
                    #     "duration": transcription_data.get("duration")
                    # }
                    logger.info(f"Voice transcribed: '{processed_data['text'][:50]}...'")
                else:
                    return {"error": "Voice transcription failed"}
                # return {"error": "Voice transcription not yet implemented"}
                    
            except Exception as e:
                logger.error(f"Voice transcription error: {str(e)}")
                return {"error": f"Voice processing failed: {str(e)}"}
        
        # Validate that we have some text to work with
        if not processed_data.get("text", "").strip():
            return {"error": "No text input provided and voice transcription failed"}

        #if text is provided in input_request, we can skip voice processing
        if has_text and not has_audio:
            processed_data['text'] = request_data['text'].strip()
        
        # Add metadata
        processed_data["session_id"] = session_id
        processed_data["request_id"] = request_id
        processed_data["processed_at"] = datetime.now().isoformat()
        processed_data["had_voice_input"] = has_audio
        processed_data["explicit_memory_complete"] = explicit_memory_complete
        
        return processed_data

    async def _create_plan(self, input_data: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        """
        Create execution plan using planner agent. Enhanced planning with session awareness
        
        Args:
            input_data: Processed input data
            request_id: Request identifier
            
        Returns:
            Planning result
        """
        logger.info(f"Creating execution plan for request {request_id}")
        
        try:
            plan_result = await self.planner.process(input_data)
            
            if plan_result.get("status") == "success":
                plan_data = plan_result.get("data", {})
                
                # Log planning decision
                logger.info(f"Plan created - Intent: {plan_data.get('intent')}, "
                          f"Confidence: {plan_data.get('confidence'):.2f}, "
                          f"Agents: {plan_data.get('agents_needed')}, "
                          f"Session: {plan_data.get('session_id')}, "
                          f"State: {plan_data.get('conversation_state')}")
                
                # Check if confidence is too low
                if plan_data.get("confidence", 0) < 0.3:
                    logger.warning(f"Low confidence plan ({plan_data.get('confidence'):.2f}) for request {request_id}")
                
                return {"data": plan_data}
            else:
                return {"error": "Planning failed"}
                
        except Exception as e:
            logger.error(f"Planning error for request {request_id}: {str(e)}")
            return {"error": f"Planning failed: {str(e)}"}

    async def _execute_plan(self, plan: Dict[str, Any], input_data: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        """
        Execute the plan using plan executor
        
        Args:
            plan: Execution plan from planner agent
            input_data: Original input data
            request_id: Request identifier
            
        Returns:
            Execution result
        """
        logger.info(f"Executing plan for request {request_id}")
        
        try:
            # Combine plan and input data for execution
            execution_context = {
                **input_data,
                "plan": plan,
                "request_id": request_id,
                # Session context for executor
                "session_id": plan.get("session_id"),
                "conversation_state": plan.get("conversation_state"),
                "has_pending_memory": plan.get("has_pending_memory", False)
            }
            
            #TODO: Implement plan executor logic
            result = await self.executor.execute_plan(plan, execution_context)
            
            if result.get("success"):
                logger.info(f"Plan executed successfully for request {request_id}")
                return result
            else:
                logger.error(f"Plan execution failed for request {request_id}: {result.get('error')}")
                return {"error": result.get("error", "Execution failed")}
                
        except Exception as e:
            logger.error(f"Execution error for request {request_id}: {str(e)}")
            return {"error": f"Execution failed: {str(e)}"}

    def _create_success_response(self, request_id: str, result: Dict[str, Any], 
                               plan: Dict[str, Any], processing_time: float) -> Dict[str, Any]:
        """Create standardized success response
        
            Enhanced response with session information
        """
        return {
            "success": True,
            "request_id": request_id,
            "result": result.get("data", result),
            # Session information
            "session_id": plan.get("session_id"),
            "conversation_state": plan.get("conversation_state"),
            "awaiting_input": plan.get("awaiting_input"),
            "has_pending_memory": plan.get("has_pending_memory", False),
            "pending_memory_id": plan.get("pending_memory_id"),
            "metadata": {
                "intent": plan.get("intent"),
                "confidence": plan.get("confidence"),
                "agents_used": plan.get("agents_needed"),
                "processing_time_seconds": processing_time,
                "timestamp": datetime.now().isoformat()
            }
        }

    def _create_error_response(self, request_id: str, error_message: str) -> Dict[str, Any]:
        """Create standardized error response"""
        return {
            "success": False,
            "request_id": request_id,
            "error": error_message,
            "timestamp": datetime.now().isoformat()
        }

    def _track_request(self, request_id: str, original_request: Dict[str, Any], 
                      plan: Dict[str, Any], result: Dict[str, Any], processing_time: float):
        """Track request for analytics and debugging
        
            Enhanced request tracking with session info
        """
        self.request_count += 1
        
        # Keep only last 100 requests in memory
        if len(self.processing_history) >= 100:
            self.processing_history.pop(0)
        
        self.processing_history.append({
            "request_id": request_id,
            "user_id": original_request.get("user_id"),
            "session_id": plan.get("session_id"),
            "intent": plan.get("intent"),
            "confidence": plan.get("confidence"),
            "agents_used": plan.get("agents_needed"),
            "conversation_state": plan.get("conversation_state"),
            "success": result.get("success", False),
            "processing_time": processing_time,
            "timestamp": datetime.now(),
            "had_voice": original_request.get("had_voice_input", False)
        })

    async def get_session_stats(self) -> Dict[str, Any]:
        """Get session-specific statistics"""
        session_stats = await self.session_manager.get_session_stats()
        return session_stats

    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics (enhanced with session info)"""
        if not self.processing_history:
            return {"total_requests": 0}
        
        successful_requests = sum(1 for req in self.processing_history if req["success"])
        avg_processing_time = sum(req["processing_time"] for req in self.processing_history) / len(self.processing_history)
        
        # Intent distribution
        intent_counts = {}
        for req in self.processing_history:
            intent = req["intent"]
            intent_counts[intent] = intent_counts.get(intent, 0) + 1

        # Session statistics
        session_count = len(set(req["session_id"] for req in self.processing_history if req.get("session_id")))
        
        return {
            "total_requests": self.request_count,
            "recent_requests": len(self.processing_history),
            "success_rate": successful_requests / len(self.processing_history),
            "average_processing_time": avg_processing_time,
            "intent_distribution": intent_counts,
            "voice_requests": sum(1 for req in self.processing_history if req["had_voice"]),
            "unique_sessions": session_count,
            "session_enabled": True
        }

    async def health_check(self) -> Dict[str, Any]:
        """Health check for the input processor (enhanced with session manager)"""
        try:
            # Test planner
            test_result = await self.planner.process({
                "text": "test", 
                "user_id": "health_check_user"
            })
            planner_healthy = test_result.get("status") == "success"
            
            # Test session manager
            session_stats = await self.session_manager.get_session_stats()
            session_healthy = isinstance(session_stats, dict)
            
            return {
                "status": "healthy" if (planner_healthy and session_healthy) else "degraded",
                "components": {
                    "planner": "healthy" if planner_healthy else "error",
                    "session_manager": "healthy" if session_healthy else "error",
                    "voice_agent": "not_implemented",
                    "executor": "not_implemented"
                },
                "stats": self.get_stats(),
                "session_stats": session_stats
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }
        
    async def close_session(self, session_id: str, user_id: str = None) -> Dict[str, Any]:
        """
        Close a specific session (called when user clicks close/exit button)
        
        Args:
            session_id: Session to close
            user_id: Optional user verification for security
            
        Returns:
            Success/failure response with session cleanup info
        """
        try:
            # Get session before closing for validation
            session = await self.session_manager.get_session(session_id)
            
            if not session:
                return {
                    "success": False,
                    "error": "Session not found or already expired",
                    "session_id": session_id
                }
            
            # Optional user verification
            if user_id and session.user_id != user_id:
                logger.warning(f"User {user_id} attempted to close session {session_id} owned by {session.user_id}")
                return {
                    "success": False,
                    "error": "Not authorized to close this session",
                    "session_id": session_id
                }
            
            # Handle incomplete memory if exists
            incomplete_memory_info = None
            if session.pending_memory and not session.pending_memory.complete:
                incomplete_memory_info = {
                    "memory_id": session.pending_memory.id,
                    "content_preview": session.pending_memory.content[:100] + "..." if len(session.pending_memory.content) > 100 else session.pending_memory.content,
                    "saved_as_incomplete": True
                }
                logger.info(f"Session {session_id} closed with incomplete memory {session.pending_memory.id}")
            
            # Close the session
            success = await self.session_manager.end_session(session_id, reason="user_requested")
            
            if success:
                logger.info(f"Session {session_id} closed by user request")
                
                # Track session closure
                self._track_session_closure(session_id, session.user_id, incomplete_memory_info)
                
                return {
                    "success": True,
                    "message": "Session closed successfully",
                    "session_id": session_id,
                    "session_duration_minutes": (datetime.now() - session.created_at).total_seconds() / 60,
                    "incomplete_memory": incomplete_memory_info,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to close session",
                    "session_id": session_id
                }
                
        except Exception as e:
            logger.error(f"Error closing session {session_id}: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to close session: {str(e)}",
                "session_id": session_id
            }

    async def close_all_user_sessions(self, user_id: str) -> Dict[str, Any]:
        """
        Close all active sessions for a user (useful for logout or cleanup)
        
        Args:
            user_id: User whose sessions to close
            
        Returns:
            Summary of closed sessions
        """
        try:
            user_sessions = await self.session_manager.get_user_sessions(user_id)
            
            if not user_sessions:
                return {
                    "success": True,
                    "message": "No active sessions found",
                    "user_id": user_id,
                    "closed_sessions": 0
                }
            
            closed_sessions = []
            failed_closures = []
            
            for session in user_sessions:
                try:
                    result = await self.close_session(session.session_id, user_id)
                    if result["success"]:
                        closed_sessions.append({
                            "session_id": session.session_id,
                            "duration_minutes": result.get("session_duration_minutes", 0),
                            "had_incomplete_memory": result.get("incomplete_memory") is not None
                        })
                    else:
                        failed_closures.append({
                            "session_id": session.session_id,
                            "error": result.get("error", "Unknown error")
                        })
                except Exception as e:
                    failed_closures.append({
                        "session_id": session.session_id,
                        "error": str(e)
                    })
            
            logger.info(f"Closed {len(closed_sessions)} sessions for user {user_id}")
            
            return {
                "success": True,
                "message": f"Closed {len(closed_sessions)} sessions",
                "user_id": user_id,
                "closed_sessions": len(closed_sessions),
                "failed_closures": len(failed_closures),
                "session_details": closed_sessions,
                "failures": failed_closures if failed_closures else None,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error closing all sessions for user {user_id}: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to close user sessions: {str(e)}",
                "user_id": user_id
            }

    def _track_session_closure(self, session_id: str, user_id: str, incomplete_memory_info: Dict = None):
        """Track session closures for analytics"""
        if len(self.processing_history) >= 100:
            self.processing_history.pop(0)
        
        self.processing_history.append({
            "event_type": "session_closed",
            "session_id": session_id,
            "user_id": user_id,
            "had_incomplete_memory": incomplete_memory_info is not None,
            "incomplete_memory_id": incomplete_memory_info.get("memory_id") if incomplete_memory_info else None,
            "timestamp": datetime.now()
        })

    async def get_session_info(self, session_id: str, user_id: str = None) -> Dict[str, Any]:
        """
        Get information about a specific session (useful for debugging or user info)
        
        Args:
            session_id: Session to get info about
            user_id: Optional user verification
            
        Returns:
            Session information or error
        """
        try:
            session = await self.session_manager.get_session(session_id)
            
            if not session:
                return {
                    "success": False,
                    "error": "Session not found or expired",
                    "session_id": session_id
                }
            
            # Optional user verification
            if user_id and session.user_id != user_id:
                return {
                    "success": False,
                    "error": "Not authorized to view this session",
                    "session_id": session_id
                }
            
            # Calculate session duration
            duration_minutes = (datetime.now() - session.created_at).total_seconds() / 60
            
            return {
                "success": True,
                "session_info": {
                    "session_id": session.session_id,
                    "user_id": session.user_id,
                    "created_at": session.created_at.isoformat(),
                    "duration_minutes": round(duration_minutes, 2),
                    "conversation_state": session.conversation_state.value,
                    "awaiting_input": session.awaiting_input.value if session.awaiting_input else None,
                    "has_pending_memory": session.pending_memory is not None,
                    "conversation_turns": len(session.conversation_history),
                    "last_activity": session.last_activity.isoformat(),
                    "recent_intents": await self.session_manager.get_recent_intents(session_id, 3)
                },
                "pending_memory": {
                    "id": session.pending_memory.id,
                    "content_preview": session.pending_memory.content[:150] + "..." if len(session.pending_memory.content) > 150 else session.pending_memory.content,
                    "confidence_score": session.pending_memory.confidence_score,
                    "questions_asked": len(session.pending_memory.follow_up_questions_asked)
                } if session.pending_memory else None
            }
            
        except Exception as e:
            logger.error(f"Error getting session info for {session_id}: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to get session info: {str(e)}",
                "session_id": session_id
            }

    async def cleanup(self):
        """Cleanup resources"""
        if hasattr(self.session_manager, '_cleanup_task') and self.session_manager._cleanup_task:
            self.session_manager._cleanup_task.cancel()