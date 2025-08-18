import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
import google.generativeai as genai
from dotenv import load_dotenv
from .base_agent import BaseAgent
from core.sessionManager import SessionManager

load_dotenv()
os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
logger = logging.getLogger(__name__)

class ResponseAgent(BaseAgent):
    def __init__(self, session_manager: SessionManager):
        super().__init__(name="ResponseAgent")
        self.session_manager = session_manager
        try:
            self.gemini_model = genai.GenerativeModel('gemini-1.5-flash')
            logger.info("ResponseAgent initialized with Gemini")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini: {e}")
            self.gemini_model = None
    
    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            user_text = input_data.get("text", "")
            session_id = input_data.get("session_id")
            instruction = input_data.get("instruction", "")
            memory_result = input_data.get("accumulated_data", {}).get("memory_result", {})

            session = None
            if session_id:
                session = await self.session_manager.get_session(session_id)
            
            response_text = await self._generate_response(
                user_text, instruction, memory_result, session, 
                input_data.get("context", {})
            )
            
            if session:
                await self.session_manager.add_to_conversation_history(session_id, {
                    "type": "assistant_response",
                    "content": response_text
                })
            
            return self._create_response({
                "response_text": response_text,
                "session_state": str(session.conversation_state.value) if (session and hasattr(session, 'conversation_state')) else "active"
            })
            
        except Exception as e:
            logger.error(f"ResponseAgent error: {e}")
            return self._create_response({
                "response_text": "I'm here to help with your memories. What would you like to share or find?",
                "error": str(e)
            })
    
    async def _generate_response(self, user_text: str, instruction: str, 
                               memory_result: Dict[str, Any], session, context: Dict[str, Any] = None) -> str:
        if not self.gemini_model:
            return self._get_fallback_response(instruction, memory_result)
        
        # Determine if this is QUERY or STORE based on memory_result action
        action = memory_result.get("action", "")
        
        if action == "memory_searched":
            # CASE 1: USER WANTS TO QUERY/FIND A MEMORY
            results = memory_result.get("results", [])
            search_query = memory_result.get("query", user_text)
            
            if results and len(results) > 0:
                # Found memories - answer their question
                memory_info = results[0]  # Use best match
                prompt = f"""
User asked: "{search_query}"
Found memory: {memory_info.get('content', '')}

Answer their question using this memory information. Be direct and helpful.
"""
            else:
                # No memories found
                prompt = f"""
User asked: "{search_query}"
No memories found.

Say: "I don't have any memories about that yet. Would you like to tell me about it so I can remember for next time?"
"""
        
        else:
            # CASE 2: USER WANTS TO STORE A MEMORY
            if action == "memory_completed":
                prompt = f"User shared: '{user_text}' - Memory saved successfully. Acknowledge warmly."
            elif action in ["memory_started", "memory_continued"]:
                questions = memory_result.get("suggested_questions", [])
                prompt = f"User is sharing: '{user_text}' - Ask a follow-up question: {questions[0] if questions else 'Can you tell me more details?'}"
            else:
                prompt = f"User wants to share: '{user_text}' - Help them store this memory."
        
        try:
            response = self.gemini_model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"Gemini failed: {e}")
            return self._get_fallback_response(instruction, memory_result)
    
    def _get_fallback_response(self, instruction: str, memory_result: Dict[str, Any]) -> str:
        if memory_result:
            action = memory_result.get("action", "")
            
            if action == "memory_started":
                questions = memory_result.get("suggested_questions", [])
                return f"Got it! {questions[0] if questions else 'Can you tell me more?'}"
            elif action == "memory_completed":
                return "Perfect! I've saved that memory."
            elif action == "memory_searched":
                results = memory_result.get("results", [])
                if not results:
                    return "I don't have any memories about that yet. Want to tell me about it?"
                return f"Here's what I found: {results[0].get('content', '')[:100]}..."
        
        return "I'm here to help with your memories. What's on your mind?"