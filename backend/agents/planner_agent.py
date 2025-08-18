from .base_agent import BaseAgent
from core.sessionManager import SessionManager, ConversationState, InputType
from typing import Any, Dict, List, Tuple, Optional
import logging
import json
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)

class PlannerAgent(BaseAgent):
    """
    AI-Enhanced Planner Agent - The intelligent "brain" of the system.
    Uses AI models to analyze user input and create optimal execution plans.
    Falls back to rule-based approach when AI is unavailable.
    """

    def __init__(self, session_manager: SessionManager, ai_client=None):
        super().__init__('planner')
        self.session_manager = session_manager
        self.ai_client = ai_client
        self.use_ai = ai_client is not None
        
        # Available agents and their capabilities
        self.available_agents = {
            "memory_agent": "Handles memory storage, retrieval, and management",
            "response_agent": "Generates conversational responses to users",
            "voice_agent": "Processes audio/speech input and transcription",
            "vision_agent": "Analyzes images and visual content",
            "context_agent": "Gathers contextual information for memory enrichment",
            "emotion_agent": "Detects emotional context and sentiment",
            "summary_agent": "Summarizes long conversations and memories"
        }
        
        # Supported intents
        self.supported_intents = [
            "store_memory", "continue_memory", "complete_memory", 
            "query_memory", "general_conversation", "clarification_needed"
        ]
        
        # Fallback keyword patterns (used when AI is unavailable)
        self.fallback_keywords = {
            "store": [
                "save", "capture", "record", "store", "note", "remember this",
                "I met", "I went", "I did", "I saw", "happened", "today",
                "yesterday", "just", "had a", "attended", "visited"
            ],
            "query": [
                "remember", "who", "what", "when", "where", "how", "recall", "find",
                "tell me about", "remind me", "what did", "who was",
                "do you remember", "can you find", "search for"
            ],
            "continuation": [
                "yes", "yeah", "also", "and", "additionally", "plus",
                "more", "furthermore", "too", "as well", "another thing"
            ],
            "completion": [
                "that's all", "that's it", "nothing else", "save it",
                "done", "finished", "complete", "got it", "perfect",
                "thanks", "thank you", "end", "stop"
            ]
        }

    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main planning logic with AI enhancement and fallback
        """
        try:
            # Extract basic information
            user_text = input_data.get('text', '').strip()
            session_id = input_data.get('session_id')
            user_id = input_data.get('user_id')
            
            logger.info(f"PlannerAgent processing - user_id: {user_id}, session_id: {session_id}")

            if not user_id:
                raise ValueError("user_id is required for session management")
            
            # Get or create session
            session = await self._get_or_create_session(session_id, user_id, input_data)
            
            # Classify intent using AI or fallback
            intent, confidence = await self._classify_intent(user_text, session)
            
            # Track intent in session
            await self.session_manager.add_intent_to_history(session.session_id, intent, confidence)
            
            # Select optimal agents
            agents_needed = await self._select_agents(intent, input_data, session)
            
            # Create execution plan
            execution_plan = await self._create_execution_plan(intent, agents_needed, session, input_data)
            
            # Add user input to conversation history
            await self.session_manager.add_to_conversation_history(session.session_id, {
                "type": "user_input",
                "content": user_text,
                "intent": intent,
                "confidence": confidence,
                "has_audio": bool(input_data.get("audio_data") or input_data.get("audio_url")),
                "has_image": bool(input_data.get("photo_url") or input_data.get("image_url")),
                "timestamp": datetime.now().isoformat()
            })
            
            # Build response
            plan_data = {
                "intent": intent,
                "confidence": confidence,
                "agents_needed": agents_needed,
                "execution_plan": execution_plan,
                "user_text": user_text,
                "session_id": session.session_id,
                "conversation_state": session.conversation_state.value,
                "awaiting_input": session.awaiting_input.value if session.awaiting_input else None,
                "has_pending_memory": session.pending_memory is not None,
                "pending_memory_id": session.pending_memory.id if session.pending_memory else None,
                "ai_enhanced": self.use_ai,
                "processing_timestamp": datetime.now().isoformat()
            }
            
            return self._create_response(plan_data)
            
        except Exception as e:
            logger.error(f"PlannerAgent error: {e}")
            return self._handle_error(e)

    async def _classify_intent(self, text: str, session) -> Tuple[str, float]:
        """
        Classify user intent using AI with fallback to rule-based approach
        """
        if self.use_ai:
            try:
                return await self._classify_intent_with_ai(text, session)
            except Exception as e:
                logger.warning(f"AI intent classification failed, using fallback: {e}")
        
        # Fallback to rule-based classification
        return await self._classify_intent_fallback(text, session)

    async def _classify_intent_with_ai(self, text: str, session) -> Tuple[str, float]:
        """
        Use AI model for intelligent intent classification
        """
        # Get recent conversation context
        recent_history = session.conversation_history[-5:] if session.conversation_history else []
        
        prompt = f"""
        Analyze this user input and classify the intent. Consider the full conversation context.
        
        USER INPUT: "{text}"
        
        CURRENT SESSION STATE:
        - Conversation State: {session.conversation_state.value}
        - Has Pending Memory: {session.pending_memory is not None}
        - Awaiting Input: {session.awaiting_input.value if session.awaiting_input else None}
        - Total Turns: {len(session.conversation_history)}
        
        RECENT CONVERSATION:
        {json.dumps(recent_history, indent=2) if recent_history else "No previous conversation"}
        
        POSSIBLE INTENTS:
        - store_memory: User wants to save/record something that happened to them
        - query_memory: User wants to recall/search for past memories or information
        - continue_memory: User is adding more details to an existing memory being built
        - complete_memory: User indicates they're done building the current memory
        - general_conversation: General chat, greetings, questions not about memories
        - clarification_needed: Input is unclear and needs clarification
        
        CLASSIFICATION RULES:
        1. If building memory and user adds details → continue_memory
        2. If building memory and user says "done"/"that's it" → complete_memory  
        3. If user describes events/experiences → store_memory
        4. If user asks about past events → query_memory
        5. If greeting or general question → general_conversation
        6. If ambiguous or unclear → clarification_needed
        
        IMPORTANT: Return ONLY raw JSON, no markdown, no code blocks, no extra text.
        {{"intent": "store_memory", "confidence": 0.9, "reasoning": "User describing meeting"}}
        """
        
        try:
            response = self.ai_client.generate_content(prompt,
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 200
                })

            result = json.loads(response.text.strip())
            
            # Validate response
            intent = result.get("intent", "general_conversation")
            confidence = float(result.get("confidence", 0.5))
            
            if intent not in self.supported_intents:
                logger.warning(f"AI returned unsupported intent: {intent}")
                intent = "general_conversation"
                confidence = 0.5
            
            logger.info(f"AI classified intent: {intent} (confidence: {confidence})")
            return intent, max(0.0, min(1.0, confidence))
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse AI intent response: {e}")
            raise

    async def _classify_intent_fallback(self, text: str, session) -> Tuple[str, float]:
        """
        Fallback rule-based intent classification
        """
        text_lower = text.lower()
        
        # Handle empty text
        if not text_lower:
            return "general_conversation", 0.3
        
        # Session-aware classification
        if session.conversation_state == ConversationState.BUILDING_MEMORY:
            if any(keyword in text_lower for keyword in self.fallback_keywords["completion"]):
                return "complete_memory", 0.9
            elif any(keyword in text_lower for keyword in self.fallback_keywords["continuation"]):
                return "continue_memory", 0.8
            elif len(text.split()) > 3:  # Substantial content
                return "continue_memory", 0.7
            else:
                return "continue_memory", 0.6
        
        # Check for pending memory continuation
        if session.pending_memory:
            if any(keyword in text_lower for keyword in self.fallback_keywords["continuation"]):
                return "continue_memory", 0.8
            elif any(keyword in text_lower for keyword in self.fallback_keywords["completion"]):
                return "complete_memory", 0.9
        
        # Count keyword matches
        store_matches = sum(1 for keyword in self.fallback_keywords["store"] if keyword in text_lower)
        query_matches = sum(1 for keyword in self.fallback_keywords["query"] if keyword in text_lower)
        
        total_words = len(text.split())
        
        if store_matches > query_matches and store_matches > 0:
            confidence = min((store_matches / max(total_words, 1)) * 5, 1.0)
            return "store_memory", max(confidence, 0.6)
        elif query_matches > 0:
            confidence = min((query_matches / max(total_words, 1)) * 5, 1.0)
            return "query_memory", max(confidence, 0.6)
        elif any(q in text_lower for q in ["?", "how", "why", "help", "hello", "hi"]):
            return "general_conversation", 0.7
        else:
            return "general_conversation", 0.5

    async def _select_agents(self, intent: str, input_data: Dict[str, Any], session) -> List[str]:
        """
        Select optimal agents using AI or fallback logic
        """
        if self.use_ai:
            try:
                return await self._select_agents_with_ai(intent, input_data, session)
            except Exception as e:
                logger.warning(f"AI agent selection failed, using fallback: {e}")
        
        return self._select_agents_fallback(intent, input_data, session)

    async def _select_agents_with_ai(self, intent: str, input_data: Dict, session) -> List[str]:
        """
        AI-powered agent selection
        """
        # Prepare input analysis
        input_types = []
        if input_data.get("audio_data") or input_data.get("audio_url"):
            input_types.append("audio")
        if input_data.get("photo_url") or input_data.get("image_url"):
            input_types.append("image")
        if input_data.get("text"):
            input_types.append("text")
        
        prompt = f"""
        Select the optimal agents to handle this user request.
        
        INTENT: {intent}
        INPUT TYPES: {input_types}
        SESSION STATE: {session.conversation_state.value}
        HAS PENDING MEMORY: {session.pending_memory is not None}
        CONVERSATION TURN: {len(session.conversation_history)}
        
        AVAILABLE AGENTS:
        {json.dumps(self.available_agents, indent=2)}
        
        SELECTION CRITERIA:
        - Choose agents needed for the specific intent
        - Consider input types (audio needs voice_agent, images need vision_agent)
        - Order agents by execution dependency
        - Include context_agent for memory building if not already enriched
        - Always include response_agent for user interaction
        
        Return ONLY raw JSON array of agent names in optimal execution order, no markdown, no code blocks, no extra text.
        ["agent1", "agent2", "agent3"]
        """
        
        try:
            response = self.ai_client.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 150
                }
            )

            agents = json.loads(response.text.strip())
            
            # Validate agents
            valid_agents = []
            for agent in agents:
                if agent in self.available_agents:
                    valid_agents.append(agent)
                else:
                    logger.warning(f"AI selected invalid agent: {agent}")
            
            # Ensure at least response_agent is included
            if not valid_agents or "response_agent" not in valid_agents:
                valid_agents.append("response_agent")
            
            return valid_agents
            
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to parse AI agent selection: {e}")
            raise

    def _select_agents_fallback(self, intent: str, input_data: Dict[str, Any], session) -> List[str]:
        """
        Fallback rule-based agent selection
        """
        # Base agent mapping
        agent_map = {
            "store_memory": ["memory_agent", "response_agent"],
            "continue_memory": ["memory_agent", "response_agent"],
            "complete_memory": ["memory_agent", "response_agent"],
            "query_memory": ["memory_agent", "response_agent"],
            "general_conversation": ["response_agent"],
            "clarification_needed": ["response_agent"]
        }
        
        agents = agent_map.get(intent, ["response_agent"]).copy()
        
        # Add specialized agents based on input
        if input_data.get("audio_data") or input_data.get("audio_url"):
            agents.insert(0, "voice_agent")
        
        if input_data.get("photo_url") or input_data.get("image_url"):
            agents.insert(-1, "vision_agent")
        
        # Add context agent for memory building if needed
        if intent in ["store_memory", "continue_memory"] and not session.context.get("enriched"):
            agents.insert(-1, "context_agent")
        
        return agents

    async def _create_execution_plan(self, intent: str, agents: List[str], session, input_data: Dict) -> Dict[str, Any]:
        """
        Create intelligent execution plan
        """
        if self.use_ai:
            try:
                return await self._create_ai_execution_plan(intent, agents, session, input_data)
            except Exception as e:
                logger.warning(f"AI execution planning failed, using fallback: {e}")
        
        return self._create_fallback_execution_plan(intent, agents, session)

    async def _create_ai_execution_plan(self, intent: str, agents: List[str], session, input_data: Dict) -> Dict[str, Any]:
        """
        Generate intelligent execution plan using AI
        """
        prompt = f"""
        Create an optimal execution plan for these agents to handle the user's request.
        
        INTENT: {intent}
        SELECTED AGENTS: {agents}
        SESSION STATE: {session.conversation_state.value}
        HAS PENDING MEMORY: {session.pending_memory is not None}
        CONVERSATION TURN: {len(session.conversation_history)}
        
        AGENT CAPABILITIES:
        {json.dumps(self.available_agents, indent=2)}
        
        PLAN REQUIREMENTS:
        - Define execution type (sequential or parallel)
        - Create detailed steps with specific instructions
        - Consider agent dependencies and optimal order
        - Include error handling and fallback strategies
        - Set appropriate timeouts and retry policies
        
        IMPORTANT: Return ONLY valid JSON with no additional text or explanation. The response must start with {{ and end with }}.

        Return JSON execution plan:
        {{
            "type": "sequential",
            "steps": [
                {{
                    "agent": "agent_name",
                    "action": "process",
                    "instruction": "Detailed instruction for the agent",
                    "timeout": 30,
                    "retry_policy": "exponential_backoff|none",
                    "priority": "high|medium|low"
                }}
            ],
            "fallback_strategy": "What to do if plan fails",
            "success_criteria": "How to measure success"
        }}
        """
        
        try:
            response = self.ai_client.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 400
                }
            )
            plan = json.loads(response.text.strip())
            
            # Validate plan structure
            if not self._validate_ai_plan(plan):
                raise ValueError("Invalid plan structure from AI")
            
            # Add session context
            plan["session_context"] = {
                "state": session.conversation_state.value,
                "has_pending_memory": session.pending_memory is not None,
                "awaiting_input": session.awaiting_input.value if session.awaiting_input else None,
                "conversation_turn": len(session.conversation_history)
            }
            
            return plan
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to create AI execution plan: {e}")
            raise

    def _create_fallback_execution_plan(self, intent: str, agents: List[str], session) -> Dict[str, Any]:
        """
        Create fallback execution plan using rules
        """
        plan = {
            "type": "sequential",
            "steps": []
        }
        
        for agent_name in agents:
            step = {
                "agent": agent_name,
                "action": "process",
                "timeout": 30,
                "retry_policy": "none",
                "priority": "medium"
            }
            
            # Add specific instructions
            if agent_name == "memory_agent":
                if intent == "store_memory":
                    step["instruction"] = "Start new memory building process"
                elif intent == "continue_memory":
                    step["instruction"] = "Continue building existing memory"
                    step["memory_id"] = session.pending_memory.id if session.pending_memory else None
                elif intent == "complete_memory":
                    step["instruction"] = "Complete and save memory"
                    step["memory_id"] = session.pending_memory.id if session.pending_memory else None
                elif intent == "query_memory":
                    step["instruction"] = "Search existing memories"
                    
            elif agent_name == "response_agent":
                if session.conversation_state == ConversationState.BUILDING_MEMORY:
                    step["instruction"] = "Generate follow-up question for memory building"
                    step["context"] = "building_memory"
                else:
                    step["instruction"] = "Generate conversational response"
                
            elif agent_name == "vision_agent":
                step["instruction"] = "Analyze images and extract relevant information"
                
            elif agent_name == "voice_agent":
                step["instruction"] = "Process and transcribe speech input"
                
            elif agent_name == "context_agent":
                step["instruction"] = "Gather contextual information for memory enrichment"
            
            plan["steps"].append(step)
        
        # Add session context and metadata
        plan["session_context"] = {
            "state": session.conversation_state.value,
            "has_pending_memory": session.pending_memory is not None,
            "awaiting_input": session.awaiting_input.value if session.awaiting_input else None,
            "conversation_turn": len(session.conversation_history)
        }
        
        plan["fallback_strategy"] = "Use rule-based approach if AI components fail"
        plan["success_criteria"] = "Successful agent execution and user satisfaction"
        
        return plan

    def _validate_ai_plan(self, plan: Dict[str, Any]) -> bool:
        """
        Validate AI-generated plan structure
        """
        if not isinstance(plan, dict):
            return False
        
        if "steps" not in plan or not isinstance(plan["steps"], list):
            return False
        
        for step in plan["steps"]:
            if not isinstance(step, dict) or "agent" not in step:
                return False
            if step["agent"] not in self.available_agents:
                return False
        
        return True

    async def _get_or_create_session(self, session_id: Optional[str], user_id: str, 
                                   input_data: Dict[str, Any]) -> Any:
        """Get existing session or create new one"""
        session = None
        
        if session_id:
            session = await self.session_manager.get_session(session_id)
            if session:
                logger.debug(f"Retrieved existing session {session_id}")
        
        if not session:
            # Create new session with initial context
            initial_context = {
                "user_id": user_id,
                "created_from": "ai_planner",
                "initial_input_type": "audio" if input_data.get("audio_data") else "text",
                "ai_enhanced": self.use_ai
            }
            new_session_id = await self.session_manager.create_session(user_id, initial_context)
            session = await self.session_manager.get_session(new_session_id)
            logger.info(f"Created new session {new_session_id} for user {user_id}")
        
        return session

    # Utility methods
    def get_supported_intents(self) -> List[str]:
        """Return list of supported intents"""
        return self.supported_intents.copy()
    
    def get_available_agents(self) -> Dict[str, str]:
        """Return available agents and their descriptions"""
        return self.available_agents.copy()
    
    def is_ai_enabled(self) -> bool:
        """Check if AI enhancements are enabled"""
        return self.use_ai
    
    async def get_planning_stats(self) -> Dict[str, Any]:
        """Get planning statistics and health metrics"""
        return {
            "ai_enhanced": self.use_ai,
            "supported_intents": len(self.supported_intents),
            "available_agents": len(self.available_agents),
            "fallback_keywords": {k: len(v) for k, v in self.fallback_keywords.items()},
            "system_health": "operational"
        }