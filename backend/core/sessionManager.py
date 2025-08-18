import uuid
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import asyncio
from dataclasses import dataclass, asdict
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConversationState(Enum):
    """Possible states of a conversation session"""
    ACTIVE = "active"
    BUILDING_MEMORY = "building_memory"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    AWAITING_DETAILS = "awaiting_details"
    COMPLETED = "completed"
    EXPIRED = "expired"

class InputType(Enum):
    """Types of expected input from user"""
    MEMORY_DETAILS = "memory_details"
    CONFIRMATION = "confirmation"
    FOLLOW_UP = "follow_up"
    CALENDAR_ACTION = "calendar_action"
    CONTACT_INFO = "contact_info"

@dataclass
class PendingMemory:
    """Structure for memory being built across multiple interactions"""
    id: str
    content: str
    timestamp: str
    entities: Dict[str, Any]
    context: Dict[str, Any]
    complete: bool = False
    confidence_score: float = 0.0
    follow_up_questions_asked: List[str] = None
    user_confirmations: List[str] = None
    
    def __post_init__(self):
        if self.follow_up_questions_asked is None:
            self.follow_up_questions_asked = []
        if self.user_confirmations is None:
            self.user_confirmations = []

@dataclass
class SessionData:
    """Complete session data structure"""
    session_id: str
    user_id: str
    created_at: datetime
    last_activity: datetime
    conversation_state: ConversationState
    context: Dict[str, Any]
    pending_memory: Optional[PendingMemory]
    conversation_history: List[Dict[str, Any]]
    awaiting_input: Optional[InputType]
    metadata: Dict[str, Any]
    intent_history: List[Tuple[str, float]]  # Track intent patterns
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        data = asdict(self)
        # Convert datetime objects to ISO strings
        data['created_at'] = self.created_at.isoformat()
        data['last_activity'] = self.last_activity.isoformat()
        # Convert enums to strings
        data['conversation_state'] = self.conversation_state.value
        data['awaiting_input'] = self.awaiting_input.value if self.awaiting_input else None
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionData':
        """Create from dictionary"""
        # Convert ISO strings back to datetime
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['last_activity'] = datetime.fromisoformat(data['last_activity'])
        # Convert strings back to enums
        data['conversation_state'] = ConversationState(data['conversation_state'])
        data['awaiting_input'] = InputType(data['awaiting_input']) if data['awaiting_input'] else None
        
        # Handle pending_memory
        if data.get('pending_memory'):
            data['pending_memory'] = PendingMemory(**data['pending_memory'])
        
        return cls(**data)

class SessionManager:
    """Complete session management system"""
    
    def __init__(self, session_timeout_minutes: int = 30, max_sessions_per_user: int = 5):
        self.active_sessions: Dict[str, SessionData] = {}  # In production, use Redis
        self.user_sessions: Dict[str, List[str]] = {}  # Track sessions per user
        self.session_timeout = timedelta(minutes=session_timeout_minutes)
        self.max_sessions_per_user = max_sessions_per_user
        
        # Start cleanup task
        self._cleanup_task = None
        self._start_cleanup_task()
    
    def _start_cleanup_task(self):
        """Start background task to clean up expired sessions"""
        async def cleanup_expired_sessions():
            while True:
                try:
                    await self.cleanup_expired_sessions()
                    await asyncio.sleep(300)  # Check every 5 minutes
                except Exception as e:
                    logger.error(f"Error in session cleanup: {e}")
                    await asyncio.sleep(60)  # Wait 1 minute before retrying
        
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(cleanup_expired_sessions())
    
    async def create_session(self, user_id: str, initial_context: Dict[str, Any] = None) -> str:
        """Create a new session for user"""
        # Clean up old sessions for this user if at limit
        await self._cleanup_user_sessions(user_id)
        
        session_id = str(uuid.uuid4())
        
        session_data = SessionData(
            session_id=session_id,
            user_id=user_id,
            created_at=datetime.now(),
            last_activity=datetime.now(),
            conversation_state=ConversationState.ACTIVE,
            context=initial_context or {},
            pending_memory=None,
            conversation_history=[],
            awaiting_input=None,
            metadata={},
            intent_history=[]
        )
        
        # Store session
        self.active_sessions[session_id] = session_data
        
        # Track for user
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = []
        self.user_sessions[user_id].append(session_id)
        
        logger.info(f"Created session {session_id} for user {user_id}")
        return session_id
    
    async def get_session(self, session_id: str) -> Optional[SessionData]:
        """Get session data if exists and active"""
        session = self.active_sessions.get(session_id)
        
        if not session:
            return None
        
        # Check if expired
        if datetime.now() - session.last_activity > self.session_timeout:
            await self.end_session(session_id, reason="expired")
            return None
        
        return session
    
    async def update_session(self, session_id: str, updates: Dict[str, Any]) -> bool:
        """Update session with new data"""
        session = await self.get_session(session_id)
        if not session:
            return False
        
        # Update fields
        for key, value in updates.items():
            if hasattr(session, key):
                setattr(session, key, value)
        
        # Always update last activity
        session.last_activity = datetime.now()
        
        logger.debug(f"Updated session {session_id} with {list(updates.keys())}")
        return True
    
    async def add_to_conversation_history(self, session_id: str, message: Dict[str, Any]) -> bool:
        """Add message to conversation history"""
        session = await self.get_session(session_id)
        if not session:
            return False
        
        message_with_timestamp = {
            **message,
            "timestamp": datetime.now().isoformat()
        }
        
        session.conversation_history.append(message_with_timestamp)
        session.last_activity = datetime.now()
        
        # Keep only last 50 messages to prevent memory bloat
        if len(session.conversation_history) > 50:
            session.conversation_history = session.conversation_history[-50:]
        
        return True
    
    async def start_memory_building(self, session_id: str, initial_content: str, 
                                  entities: Dict[str, Any] = None, 
                                  context: Dict[str, Any] = None) -> Optional[PendingMemory]:
        """Start building a memory across multiple interactions"""
        session = await self.get_session(session_id)
        if not session:
            return None
        
        pending_memory = PendingMemory(
            id=str(uuid.uuid4()),
            content=initial_content,
            timestamp=datetime.now().isoformat(),
            entities=entities or {},
            context=context or {},
            complete=False,
            confidence_score=0.3  # Start with low confidence
        )
        
        # Update session state
        await self.update_session(session_id, {
            "pending_memory": pending_memory,
            "conversation_state": ConversationState.BUILDING_MEMORY,
            "awaiting_input": InputType.MEMORY_DETAILS
        })
        
        logger.info(f"Started memory building in session {session_id}, memory_id: {pending_memory.id}")
        return pending_memory
    
    async def update_pending_memory(self, session_id: str, additional_content: str,
                                  new_entities: Dict[str, Any] = None,
                                  confidence_boost: float = 0.1) -> Optional[PendingMemory]:
        """Update pending memory with new information"""
        session = await self.get_session(session_id)
        if not session or not session.pending_memory:
            return None
        
        # Update content
        session.pending_memory.content += f" {additional_content}"
        
        # Merge entities
        if new_entities:
            session.pending_memory.entities.update(new_entities)
        
        # Boost confidence
        session.pending_memory.confidence_score = min(
            session.pending_memory.confidence_score + confidence_boost, 1.0
        )
        
        session.last_activity = datetime.now()
        
        logger.debug(f"Updated pending memory {session.pending_memory.id} in session {session_id}")
        return session.pending_memory
    
    async def complete_memory(self, session_id: str) -> Optional[PendingMemory]:
        """Mark memory as complete and ready for storage"""
        session = await self.get_session(session_id)
        if not session or not session.pending_memory:
            return None
        
        session.pending_memory.complete = True
        
        # Update session state
        await self.update_session(session_id, {
            "conversation_state": ConversationState.ACTIVE,
            "awaiting_input": None
        })
        
        completed_memory = session.pending_memory
        session.pending_memory = None  # Clear pending memory
        
        logger.info(f"Completed memory {completed_memory.id} in session {session_id}")
        return completed_memory
    
    async def add_intent_to_history(self, session_id: str, intent: str, confidence: float):
        """Track intent patterns for better understanding"""
        session = await self.get_session(session_id)
        if not session:
            return
        
        session.intent_history.append((intent, confidence))
        
        # Keep only last 20 intents
        if len(session.intent_history) > 20:
            session.intent_history = session.intent_history[-20:]
    
    async def get_recent_intents(self, session_id: str, count: int = 5) -> List[Tuple[str, float]]:
        """Get recent intents for context"""
        session = await self.get_session(session_id)
        if not session:
            return []
        
        return session.intent_history[-count:]
    
    async def end_session(self, session_id: str, reason: str = "user_request") -> bool:
        """End session and cleanup"""
        session = self.active_sessions.get(session_id)
        if not session:
            return False
        
        # If there's pending memory, save it as incomplete
        if session.pending_memory and not session.pending_memory.complete:
            logger.warning(f"Session {session_id} ended with incomplete memory {session.pending_memory.id}")
            # You might want to save incomplete memories to a special collection
            # await self._save_incomplete_memory(session.pending_memory)
        
        # Remove from active sessions
        del self.active_sessions[session_id]
        
        # Remove from user sessions
        if session.user_id in self.user_sessions:
            self.user_sessions[session.user_id] = [
                sid for sid in self.user_sessions[session.user_id] if sid != session_id
            ]
        
        logger.info(f"Ended session {session_id} for user {session.user_id}, reason: {reason}")
        return True
    
    async def cleanup_expired_sessions(self):
        """Clean up expired sessions"""
        now = datetime.now()
        expired_sessions = []
        
        for session_id, session in self.active_sessions.items():
            if now - session.last_activity > self.session_timeout:
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            await self.end_session(session_id, reason="expired")
        
        if expired_sessions:
            logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")
    
    async def _cleanup_user_sessions(self, user_id: str):
        """Remove oldest sessions if user has too many"""
        if user_id not in self.user_sessions:
            return
        
        user_session_ids = self.user_sessions[user_id]
        if len(user_session_ids) >= self.max_sessions_per_user:
            # Sort by last activity and remove oldest
            sessions_with_activity = []
            for sid in user_session_ids:
                session = self.active_sessions.get(sid)
                if session:
                    sessions_with_activity.append((session.last_activity, sid))
            
            sessions_with_activity.sort()  # Oldest first
            
            # Remove oldest sessions
            to_remove = len(sessions_with_activity) - self.max_sessions_per_user + 1
            for _, session_id in sessions_with_activity[:to_remove]:
                await self.end_session(session_id, reason="user_session_limit")
    
    async def get_session_stats(self) -> Dict[str, Any]:
        """Get system statistics"""
        total_sessions = len(self.active_sessions)
        active_conversations = sum(
            1 for s in self.active_sessions.values() 
            if s.conversation_state == ConversationState.BUILDING_MEMORY
        )
        
        return {
            "total_active_sessions": total_sessions,
            "building_memory_sessions": active_conversations,
            "total_users": len(self.user_sessions),
            "average_sessions_per_user": total_sessions / max(len(self.user_sessions), 1)
        }
    
    async def get_user_sessions(self, user_id: str) -> List[SessionData]:
        """Get all active sessions for a user"""
        if user_id not in self.user_sessions:
            return []
        
        sessions = []
        for session_id in self.user_sessions[user_id]:
            session = await self.get_session(session_id)
            if session:
                sessions.append(session)
        
        return sessions

# Enhanced Planner Agent with Session Support
class SessionAwarePlannerAgent:
    """Enhanced version of your PlannerAgent with session management"""
    
    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager
        self.agent_name = 'session_aware_planner'
        
        # Your existing keywords
        self.store_keywords = [
            "remember", "save", "capture", "record", "store", "note",
            "I met", "I went", "I did", "I saw", "happened", "today",
            "yesterday", "just", "had a", "attended", "this is"
        ]
        
        self.query_keywords = [
            "who", "what", "when", "where", "how", "recall", "find",
            "tell me about", "remind me", "what did", "who was",
            "do you remember", "can you find", "search for"
        ]
        
        # Session-aware keywords
        self.continuation_keywords = [
            "yes", "yeah", "also", "and", "additionally", "plus",
            "more", "furthermore", "too", "as well"
        ]
        
        self.completion_keywords = [
            "that's all", "that's it", "nothing else", "save it",
            "done", "finished", "complete", "got it"
        ]
    
    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced process method with session awareness"""
        try:
            user_text = input_data.get('text', '').lower()
            session_id = input_data.get('session_id')
            user_id = input_data.get('user_id')
            
            # Get or create session
            session = None
            if session_id:
                session = await self.session_manager.get_session(session_id)
            
            if not session and user_id:
                session_id = await self.session_manager.create_session(user_id)
                session = await self.session_manager.get_session(session_id)
            
            if not session:
                raise ValueError("Could not create or retrieve session")
            
            # Classify intent with session context
            intent, confidence = await self._classify_intent_with_session(user_text, session)
            
            # Add intent to history
            await self.session_manager.add_intent_to_history(session_id, intent, confidence)
            
            # Select agents based on intent and session state
            agents_needed = await self._select_agents_with_session(intent, input_data, session)
            
            # Create execution plan
            execution_plan = self._create_execution_plan(intent, agents_needed, session)
            
            # Add to conversation history
            await self.session_manager.add_to_conversation_history(session_id, {
                "type": "user_input",
                "content": input_data.get("text", ""),
                "intent": intent,
                "confidence": confidence
            })
            
            plan_data = {
                "session_id": session_id,
                "intent": intent,
                "confidence": confidence,
                "agents_needed": agents_needed,
                "execution_plan": execution_plan,
                "session_state": session.conversation_state.value,
                "awaiting_input": session.awaiting_input.value if session.awaiting_input else None,
                "user_text": input_data.get("text", "")
            }
            
            return self._create_response(plan_data)
            
        except Exception as e:
            logger.error(f"Error in SessionAwarePlannerAgent.process: {e}")
            return self._handle_error(e)
    
    async def _classify_intent_with_session(self, text: str, session: SessionData) -> Tuple[str, float]:
        """Enhanced intent classification with session context"""
        if not text.strip():
            return "general_conversation", 0.3
        
        # Check session state first
        if session.conversation_state == ConversationState.BUILDING_MEMORY:
            # We're in middle of building a memory
            if any(keyword in text for keyword in self.completion_keywords):
                return "complete_memory", 0.9
            elif any(keyword in text for keyword in self.continuation_keywords):
                return "continue_memory", 0.8
            else:
                # Default to continuing memory if we're in that state
                return "continue_memory", 0.6
        
        # Check for memory continuation patterns
        if session.pending_memory and any(keyword in text for keyword in self.continuation_keywords):
            return "continue_memory", 0.7
        
        # Your existing classification logic
        store_matches = sum(1 for keyword in self.store_keywords if keyword in text)
        query_matches = sum(1 for keyword in self.query_keywords if keyword in text)
        
        total_words = len(text.split())
        
        if store_matches > query_matches and store_matches > 0:
            confidence = min((store_matches / max(total_words, 1)) * 5, 1.0)
            confidence = max(confidence, 0.6)
            return "store_memory", confidence
        elif query_matches > 0:
            confidence = min((query_matches / max(total_words, 1)) * 5, 1.0)
            confidence = max(confidence, 0.6)
            return "query_memory", confidence
        else:
            if any(q in text for q in ["?", "how", "why", "help"]):
                return "general_conversation", 0.7
            else:
                return "general_conversation", 0.5
    
    async def _select_agents_with_session(self, intent: str, input_data: Dict[str, Any], 
                                        session: SessionData) -> List[str]:
        """Enhanced agent selection with session awareness"""
        
        # Base agent selection (your existing logic)
        agent_map = {
            "store_memory": ["memory_agent", "response_agent"],
            "continue_memory": ["memory_agent", "response_agent"],
            "complete_memory": ["memory_agent", "response_agent"],
            "query_memory": ["memory_agent", "response_agent"],
            "general_conversation": ["response_agent"]
        }
        
        agents = agent_map.get(intent, ['response_agent']).copy()
        
        # Add voice agent if audio input is present
        if input_data.get("audio_data"):
            agents.insert(0, "voice_agent")
        
        # Add vision agent if photo is present
        if input_data.get("photo_url") or input_data.get("image_url"):
            agents.insert(-1, "vision_agent")
        
        # Add context agent if building memory and no context exists
        if intent in ["store_memory", "continue_memory"] and not session.context:
            agents.insert(-1, "context_agent")
        
        return agents
    
    def _create_execution_plan(self, intent: str, agents: List[str], 
                             session: SessionData) -> Dict[str, Any]:
        """Enhanced execution plan with session context"""
        plan = {
            "type": "sequential",
            "steps": [],
            "session_context": {
                "state": session.conversation_state.value,
                "has_pending_memory": session.pending_memory is not None,
                "awaiting_input": session.awaiting_input.value if session.awaiting_input else None
            }
        }
        
        for agent_name in agents:
            step = {
                "agent": agent_name,
                "action": "process"
            }
            
            # Enhanced instructions based on session state
            if agent_name == "memory_agent":
                if intent == "store_memory":
                    step["instruction"] = "Start new memory building process"
                elif intent == "continue_memory":  
                    step["instruction"] = "Continue building existing memory"
                elif intent == "complete_memory":
                    step["instruction"] = "Complete and save memory"
                elif intent == "query_memory":
                    step["instruction"] = "Search existing memories"
            
            elif agent_name == "response_agent":
                if session.conversation_state == ConversationState.BUILDING_MEMORY:
                    step["instruction"] = "Generate follow-up question for memory building"
                else:
                    step["instruction"] = "Generate conversational response"
            
            elif agent_name == "context_agent":
                step["instruction"] = "Gather contextual information for memory"
            
            plan["steps"].append(step)
        
        return plan
    
    def _create_response(self, plan_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create response with session information"""
        return {
            "status": "success",
            "agent": self.agent_name,
            "data": plan_data,
            "session_id": plan_data["session_id"],
            "timestamp": datetime.now().isoformat()
        }
    
    def _handle_error(self, error: Exception) -> Dict[str, Any]:
        """Enhanced error handling"""
        logger.error(f"PlannerAgent error: {error}")
        return {
            "status": "error",
            "agent": self.agent_name,
            "error": str(error),
            "timestamp": datetime.now().isoformat()
        }

# Usage Example
# async def main():
#     """Example usage of the complete session management system"""
    
#     # Initialize session manager
#     session_manager = SessionManager(session_timeout_minutes=30)
    
#     # Initialize planner with session support
#     planner = SessionAwarePlannerAgent(session_manager)
    
#     # Simulate the conference memory example
#     user_id = "user123"
    
#     # Message 1: Initial memory
#     input1 = {
#         "text": "I just met an amazing person at the conference",
#         "user_id": user_id
#     }
    
#     result1 = await planner.process(input1)
#     print(f"Response 1: {result1}")
#     session_id = result1["data"]["session_id"]
    
#     # Message 2: Continue building memory
#     input2 = {
#         "text": "This is Jennifer Chen, she's a VP of Engineering at Stripe",
#         "user_id": user_id,
#         "session_id": session_id,
#         "photo_url": "https://example.com/photo.jpg"
#     }
    
#     result2 = await planner.process(input2)
#     print(f"Response 2: {result2}")
    
#     # Message 3: Add more details
#     input3 = {
#         "text": "She mentioned they're hiring senior engineers and she went to Stanford like me",
#         "user_id": user_id,
#         "session_id": session_id
#     }
    
#     result3 = await planner.process(input3)
#     print(f"Response 3: {result3}")
    
#     # Message 4: Complete memory
#     input4 = {
#         "text": "Yes, remind me Tuesday morning. That's all for now.",
#         "user_id": user_id,
#         "session_id": session_id
#     }
    
#     result4 = await planner.process(input4)
#     print(f"Response 4: {result4}")
    
#     # Get session stats
#     stats = await session_manager.get_session_stats()
#     print(f"Session stats: {stats}")

# if __name__ == "__main__":
#     asyncio.run(main())