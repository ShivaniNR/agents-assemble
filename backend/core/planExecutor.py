from typing import Dict, Any, List, Optional
import logging
from datetime import datetime
import asyncio
from dataclasses import asdict

from core.sessionManager import SessionManager, ConversationState, InputType
from services.storage_service import StorageService
# Import your agents here when they're implemented
from agents.memory_agent import MemoryAgent
from backend.agents.response_agent import ResponseAgent
from backend.agents.voice_agent import VoiceAgent
# from agents.vision_agent import VisionAgent
# from agents.context_agent import ContextAgent

logger = logging.getLogger(__name__)

class PlanExecutor:
    """
    Orchestrates the execution of multi-agent plans created by the PlannerAgent.
    Handles sequential and parallel execution of agents with session management.
    """
    
    def __init__(self, session_manager: SessionManager, storage_service: StorageService):
        self.session_manager = session_manager
        self.storage_service = storage_service
        
        # Initialize agents (uncomment when implemented)
        self.memory_agent = MemoryAgent(self.session_manager, self.storage_service)
        self.response_agent = ResponseAgent(self.session_manager)
        # self.vision_agent = VisionAgent()
        self.voice_agent = VoiceAgent(self.session_manager)
        # self.context_agent = ContextAgent()
        
        # Agent registry for dynamic execution
        self.agents = {
            "memory_agent": self.memory_agent,
            "response_agent": self.response_agent,
            # "vision_agent": self.vision_agent,
            "voice_agent": self.voice_agent,
            # "context_agent": self.context_agent
        }
        
        self.execution_stats = {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "agent_usage_count": {},
            "average_execution_time": 0.0
        }

    async def execute_plan(self, plan: Dict[str, Any], execution_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main execution method that processes a plan from the PlannerAgent
        
        Args:
            plan: Execution plan from PlannerAgent containing steps and context
            execution_context: Combined input data and session context
            
        Returns:
            Execution result with agent outputs and final response
        """
        execution_id = execution_context.get("request_id", "unknown")
        execution_plan = plan.get("execution_plan", {})
        session_id = execution_context.get("session_id")
        start_time = datetime.now()
        #explicit_memory_complete = execution_context.get("explicit_memory_complete", False)
        
        logger.info(f"Starting plan execution {execution_id} for session {session_id}")
        
        try:
            self.execution_stats["total_executions"] += 1
            
            # Validate plan structure
            if not self._validate_plan(execution_plan):
                return self._create_error_result("Invalid plan structure", execution_id)
            
            logger.info(f"Valid plan structure for execution {execution_id}")

            # Execute based on plan type
            plan_type = plan.get("type", "sequential")

            if plan_type == "sequential":
                result = await self._execute_sequential_plan(execution_plan, execution_context)
            elif plan_type == "parallel":
                result = await self._execute_parallel_plan(execution_plan, execution_context)
            else:
                return self._create_error_result(f"Unknown plan type: {plan_type}", execution_id)
            
            logger.info(f"Plan execution {execution_id} completed successfully")

            # Update execution stats
            execution_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"Execution time for {execution_id}: {execution_time:.2f}s")

            self._update_execution_stats(True, execution_time, plan.get("steps", []))
            
            # Update session state based on results
            await self._update_session_from_execution(session_id, result, execution_context)
            
            logger.info(f"Plan execution {execution_id} completed successfully in {execution_time:.2f}s")
            
            return {
                "success": True,
                "execution_id": execution_id,
                "data": result,
                "execution_time": execution_time,
                "agents_executed": [step["agent"] for step in plan.get("steps", [])],
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            self._update_execution_stats(False, execution_time, execution_plan.get("steps", []))
            
            logger.error(f"Plan execution {execution_id} failed: {str(e)}")
            return self._create_error_result(str(e), execution_id)

    async def _execute_sequential_plan(self, plan: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute plan steps sequentially (one after another)
        Each agent receives the output of the previous agent
        """
        # print('plan:', plan)
        # print('\ncontext:', context)
        steps = plan.get("steps", [])
        logger.info(f'Executing sequential plan with {len(steps)} steps: {steps}')
        session_context = plan.get("session_context", {})
        
        # Initialize execution context that will be passed between agents
        agent_context = {
            **context,
            "session_context": session_context,
            "previous_outputs": {},
            "accumulated_data": {}
        }
        
        step_results = []
        final_response = None
        
        for i, step in enumerate(steps):
            agent_name = step.get("agent")
            instruction = step.get("instruction", "process")
            
            logger.debug(f"Executing step {i+1}/{len(steps)}: {agent_name} - {instruction}")
            logger.info(f"Executing step {i+1}/{len(steps)}: {agent_name} - {instruction}")
            
            try:
                # Execute the agent step
                step_result = await self._execute_agent_step(agent_name, step, agent_context)
                
                if not step_result.get("success", False):
                    logger.error(f"Agent {agent_name} failed: {step_result.get('error', 'Unknown error')}")
                    return {
                        "success": False,
                        "error": f"Agent {agent_name} failed: {step_result.get('error', 'Unknown error')}",
                        "failed_at_step": i + 1,
                        "completed_steps": step_results
                    }
                
                # Store step result
                step_results.append({
                    "step": i + 1,
                    "agent": agent_name,
                    "instruction": instruction,
                    "result": step_result,
                    "timestamp": datetime.now().isoformat()
                })
                
                # Update context with this agent's output for next agents
                agent_output = step_result.get("data", {})
                agent_context["previous_outputs"][agent_name] = agent_output
                
                # Accumulate important data
                if agent_name == "memory_agent":
                    agent_context["accumulated_data"]["memory_result"] = agent_output
                elif agent_name == "vision_agent":
                    agent_context["accumulated_data"]["vision_result"] = agent_output
                elif agent_name == "voice_agent":
                    agent_context["accumulated_data"]["voice_result"] = agent_output
                elif agent_name == "context_agent":
                    agent_context["accumulated_data"]["context_result"] = agent_output
                elif agent_name == "response_agent":
                    # Response agent typically provides the final user-facing response
                    agent_context["accumulated_data"]["response_result"] = agent_output
                    final_response = agent_output
                
                logger.debug(f"Step {i+1} completed successfully")
                
            except Exception as e:
                logger.error(f"Error executing step {i+1} ({agent_name}): {str(e)}")
                return {
                    "success": False,
                    "error": f"Step {i+1} failed: {str(e)}",
                    "failed_at_step": i + 1,
                    "completed_steps": step_results
                }
        
        return {
            "success": True,
            "step_results": step_results,
            "final_response": final_response,
            "accumulated_data": agent_context["accumulated_data"],
            "total_steps": len(steps)
        }

    async def _execute_parallel_plan(self, plan: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute plan steps in parallel (simultaneously)
        All agents receive the same initial context
        """
        steps = plan.get("steps", [])
        session_context = plan.get("session_context", {})
        
        # Prepare context for all agents
        agent_context = {
            **context,
            "session_context": session_context
        }
        
        logger.debug(f"Executing {len(steps)} steps in parallel")
        
        # Create tasks for all steps
        tasks = []
        for i, step in enumerate(steps):
            task = self._execute_agent_step(step.get("agent"), step, agent_context.copy())
            tasks.append((i, step, task))
        
        # Execute all tasks concurrently
        step_results = []
        parallel_outputs = {}
        
        try:
            # Wait for all tasks to complete
            completed_tasks = await asyncio.gather(*[task for _, _, task in tasks], return_exceptions=True)
            
            for i, (step_index, step, result) in enumerate(zip([t[0] for t in tasks], [t[1] for t in tasks], completed_tasks)):
                agent_name = step.get("agent")
                
                if isinstance(result, Exception):
                    logger.error(f"Parallel step {step_index + 1} ({agent_name}) failed: {str(result)}")
                    step_results.append({
                        "step": step_index + 1,
                        "agent": agent_name,
                        "success": False,
                        "error": str(result),
                        "timestamp": datetime.now().isoformat()
                    })
                else:
                    step_results.append({
                        "step": step_index + 1,
                        "agent": agent_name,
                        "result": result,
                        "timestamp": datetime.now().isoformat()
                    })
                    
                    if result.get("success"):
                        parallel_outputs[agent_name] = result.get("data", {})
            
            # Determine if any critical agents failed
            critical_failures = [r for r in step_results if not r.get("success", True) and r.get("agent") in ["memory_agent", "response_agent"]]
            
            if critical_failures:
                return {
                    "success": False,
                    "error": "Critical agents failed in parallel execution",
                    "step_results": step_results,
                    "critical_failures": critical_failures
                }
            
            return {
                "success": True,
                "step_results": step_results,
                "parallel_outputs": parallel_outputs,
                "total_steps": len(steps)
            }
            
        except Exception as e:
            logger.error(f"Parallel execution failed: {str(e)}")
            return {
                "success": False,
                "error": f"Parallel execution failed: {str(e)}",
                "step_results": step_results
            }

    async def _execute_agent_step(self, agent_name: str, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a single agent step with proper error handling and context
        """
        if agent_name not in self.agents:
            # For now, simulate agent execution since agents aren't implemented
            return await self._simulate_agent_execution(agent_name, step, context)
        
        agent = self.agents[agent_name]
        instruction = step.get("instruction", "process")
        
        # Prepare agent-specific context
        agent_context = {
            **context,
            "instruction": instruction,
            "step_config": step,
            "agent_name": agent_name
        }
        
        # try:
        #     # Execute the agent
        #     result = await agent.process(agent_context)
            
        #     # Standardize the response format
        #     if isinstance(result, dict) and "status" in result:
        #         return {
        #             "success": result.get("status") == "success",
        #             "data": result.get("data", {}),
        #             "agent": agent_name,
        #             "instruction": instruction
        #         }
        #     else:
        #         return {
        #             "success": True,
        #             "data": result,
        #             "agent": agent_name,
        #             "instruction": instruction
        #         }

        # Prepare agent-specific context based on agent type
        #agent_context = self._prepare_agent_context(agent_name, step, context)

        try:
            logger.info(f"Executing real agent: {agent_name} with instruction: {instruction}")
            
            # Execute the agent with the prepared context
            result = await agent.process(agent_context)
            
            # Standardize the response format
            return self._standardize_agent_response(result, agent_name, instruction)
                
        except Exception as e:
            logger.error(f"Agent {agent_name} execution error: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "agent": agent_name,
                "instruction": instruction
            }

    def _standardize_agent_response(self, result: Any, agent_name: str, instruction: str) -> Dict[str, Any]:
        """
        Standardize agent responses to a common format
        """
        # If result is already in the expected format
        if isinstance(result, dict) and "success" in result:
            return {
                **result,
                "agent": agent_name,
                "instruction": instruction
            }
        
        # If result has status field (common pattern)
        if isinstance(result, dict) and "status" in result:
            return {
                "success": result.get("status") == "success",
                "data": result.get("data", result),
                "agent": agent_name,
                "instruction": instruction,
                "error": result.get("error") if result.get("status") != "success" else None
            }
        
        # If result is a simple dict, treat as success
        if isinstance(result, dict):
            return {
                "success": True,
                "data": result,
                "agent": agent_name,
                "instruction": instruction
            }
        
        # For other types, wrap in data field
        return {
            "success": True,
            "data": {"result": result},
            "agent": agent_name,
            "instruction": instruction
        }

    async def _simulate_agent_execution(self, agent_name: str, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Simulate agent execution for development/testing purposes
        Remove this method once real agents are implemented
        """
        instruction = step.get("instruction", "process")
        session_id = context.get("session_id")
        user_text = context.get("text", "")
        
        # Simulate processing delay
        await asyncio.sleep(0.1)
        
        # Simulate different agent behaviors
        if agent_name == "memory_agent":
            return await self._simulate_memory_agent(instruction, context)
        elif agent_name == "response_agent":
            return await self._simulate_response_agent(instruction, context)
        elif agent_name == "vision_agent":
            return await self._simulate_vision_agent(instruction, context)
        elif agent_name == "voice_agent":
            return await self._simulate_voice_agent(instruction, context)
        elif agent_name == "context_agent":
            return await self._simulate_context_agent(instruction, context)
        else:
            return {
                "success": True,
                "data": {
                    "message": f"Simulated {agent_name} execution",
                    "instruction": instruction,
                    "processed_text": user_text[:50] + "..." if len(user_text) > 50 else user_text
                },
                "agent": agent_name
            }

    async def _simulate_memory_agent(self, instruction: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate memory agent behavior"""
        session_id = context.get("session_id")
        user_text = context.get("text", "")
        
        if instruction == "Start new memory building process":
            # Start building a memory
            memory_content = user_text
            entities = {"person": [], "organization": [], "event": []}  # Simulated entity extraction
            
            pending_memory = await self.session_manager.start_memory_building(
                session_id, memory_content, entities, {"source": "user_input"}
            )
            
            return {
                "success": True,
                "data": {
                    "action": "memory_started",
                    "memory_id": pending_memory.id if pending_memory else None,
                    "content_preview": memory_content[:100] + "..." if len(memory_content) > 100 else memory_content,
                    "needs_more_details": True
                }
            }
            
        elif instruction == "Continue building existing memory":
            # Add to existing memory
            memory_id = context.get("step_config", {}).get("memory_id")
            pending_memory = await self.session_manager.update_pending_memory(
                session_id, user_text, confidence_boost=0.2
            )
            
            return {
                "success": True,
                "data": {
                    "action": "memory_continued",
                    "memory_id": pending_memory.id if pending_memory else None,
                    "confidence": pending_memory.confidence_score if pending_memory else 0.0,
                    "content_preview": pending_memory.content[:100] + "..." if pending_memory and len(pending_memory.content) > 100 else pending_memory.content if pending_memory else ""
                }
            }
            
        elif instruction == "Complete and save memory":
            # Complete the memory
            completed_memory = await self.session_manager.complete_memory(session_id)
            
            return {
                "success": True,
                "data": {
                    "action": "memory_completed",
                    "memory_id": completed_memory.id if completed_memory else None,
                    "final_content": completed_memory.content if completed_memory else "",
                    "confidence": completed_memory.confidence_score if completed_memory else 0.0
                }
            }
            
        elif instruction == "Search existing memories":
            # Simulate memory search
            return {
                "success": True,
                "data": {
                    "action": "memory_searched",
                    "query": user_text,
                    "results": [
                        {
                            "memory_id": "mem_123",
                            "content": "Previous conference meeting with Jennifer Chen from Stripe",
                            "relevance_score": 0.8,
                            "timestamp": "2024-01-15T10:30:00Z"
                        }
                    ]
                }
            }
        
        return {
            "success": True,
            "data": {
                "action": "memory_processed",
                "instruction": instruction
            }
        }

    async def _simulate_response_agent(self, instruction: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate response agent behavior"""
        user_text = context.get("text", "")
        session_context = context.get("session_context", {})
        previous_outputs = context.get("previous_outputs", {})
        
        if instruction == "Generate follow-up question for memory building":
            # Generate a follow-up question to get more details
            memory_result = previous_outputs.get("memory_agent", {})
            
            questions = [
                "Can you tell me more about this person or event?",
                "What was the context or setting when this happened?",
                "Are there any important details I should remember about this?",
                "Would you like me to set any reminders related to this?"
            ]
            
            return {
                "success": True,
                "data": {
                    "response_type": "follow_up_question",
                    "message": questions[0],  # In reality, would be more intelligent
                    "awaiting_response": True,
                    "context": "memory_building"
                }
            }
            
        elif instruction == "Generate conversational response":
            # Generate a regular conversational response
            memory_result = previous_outputs.get("memory_agent", {})
            
            if memory_result.get("action") == "memory_completed":
                message = "Great! I've saved that memory for you. I'll be able to help you recall these details later."
            elif memory_result.get("action") == "memory_searched":
                results = memory_result.get("results", [])
                if results:
                    message = f"I found {len(results)} related memories. Here's what I remember: {results[0]['content']}"
                else:
                    message = "I couldn't find any related memories for your query."
            else:
                message = "I understand. How can I help you further?"
            
            return {
                "success": True,
                "data": {
                    "response_type": "conversational",
                    "message": message,
                    "awaiting_response": False
                }
            }
        
        return {
            "success": True,
            "data": {
                "response_type": "general",
                "message": "I'm here to help!",
                "instruction": instruction
            }
        }

    async def _simulate_vision_agent(self, instruction: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate vision agent behavior"""
        photo_url = context.get("photo_url") or context.get("image_url")
        
        if photo_url:
            # Simulate image analysis
            return {
                "success": True,
                "data": {
                    "image_analyzed": True,
                    "detected_objects": ["person", "indoor_setting", "professional_attire"],
                    "text_detected": "Jennifer Chen - VP Engineering",
                    "confidence": 0.85,
                    "description": "Professional headshot of a person in business attire"
                }
            }
        else:
            return {
                "success": True,
                "data": {
                    "image_analyzed": False,
                    "message": "No image provided for analysis"
                }
            }

    async def _simulate_voice_agent(self, instruction: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate voice agent behavior"""
        audio_data = context.get("audio_data")
        
        if audio_data:
            # Simulate speech processing
            return {
                "success": True,
                "data": {
                    "transcription": context.get("text", "Simulated transcription"),
                    "confidence": 0.9,
                    "language": "en-US",
                    "duration": 5.2
                }
            }
        else:
            return {
                "success": True,
                "data": {
                    "message": "No audio data provided"
                }
            }

    async def _simulate_context_agent(self, instruction: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate context agent behavior"""
        user_text = context.get("text", "")
        
        # Simulate context gathering
        return {
            "success": True,
            "data": {
                "context_gathered": True,
                "location": "San Francisco, CA",
                "time_context": "business_hours",
                "relevant_entities": ["conference", "networking", "professional"],
                "suggested_tags": ["work", "networking", "important_contact"]
            }
        }

    async def _update_session_from_execution(self, session_id: str, execution_result: Dict[str, Any], 
                                           context: Dict[str, Any]):
        """Update session state based on execution results"""
        if not session_id or not execution_result.get("success"):
            return
        
        try:
            # Add execution result to conversation history
            await self.session_manager.add_to_conversation_history(session_id, {
                "type": "agent_execution",
                "result": execution_result,
                "context": "plan_execution"
            })
            
            # Update session state based on memory operations
            if execution_result.get("accumulated_data", {}).get("memory_result"):
                memory_result = execution_result["accumulated_data"]["memory_result"]
                
                if memory_result.get("action") == "memory_started":
                    await self.session_manager.update_session(session_id, {
                        "conversation_state": ConversationState.BUILDING_MEMORY,
                        "awaiting_input": InputType.MEMORY_DETAILS
                    })
                elif memory_result.get("action") == "memory_completed":
                    await self.session_manager.update_session(session_id, {
                        "conversation_state": ConversationState.ACTIVE,
                        "awaiting_input": None
                    })
            
        except Exception as e:
            logger.error(f"Error updating session {session_id} from execution: {str(e)}")

    def _validate_plan(self, plan: Dict[str, Any]) -> bool:
        """Validate plan structure"""
        if not isinstance(plan, dict):
            return False
        
        if "steps" not in plan or not isinstance(plan["steps"], list):
            return False
        
        for step in plan["steps"]:
            if not isinstance(step, dict) or "agent" not in step:
                return False
        
        return True

    def _update_execution_stats(self, success: bool, execution_time: float, steps: List[Dict[str, Any]]):
        """Update execution statistics"""
        if success:
            self.execution_stats["successful_executions"] += 1
        else:
            self.execution_stats["failed_executions"] += 1
        
        # Update average execution time
        total_executions = self.execution_stats["total_executions"]
        current_avg = self.execution_stats["average_execution_time"]
        self.execution_stats["average_execution_time"] = (
            (current_avg * (total_executions - 1) + execution_time) / total_executions
        )
        
        # Update agent usage counts
        for step in steps:
            agent_name = step.get("agent")
            if agent_name:
                self.execution_stats["agent_usage_count"][agent_name] = (
                    self.execution_stats["agent_usage_count"].get(agent_name, 0) + 1
                )

    def _create_error_result(self, error_message: str, execution_id: str) -> Dict[str, Any]:
        """Create standardized error result"""
        self.execution_stats["failed_executions"] += 1
        
        return {
            "success": False,
            "execution_id": execution_id,
            "error": error_message,
            "timestamp": datetime.now().isoformat()
        }

    def get_execution_stats(self) -> Dict[str, Any]:
        """Get execution statistics"""
        return {
            **self.execution_stats,
            "success_rate": (
                self.execution_stats["successful_executions"] / 
                max(self.execution_stats["total_executions"], 1)
            )
        }

    async def health_check(self) -> Dict[str, Any]:
        """Health check for the plan executor"""
        try:
            # Test basic functionality
            test_plan = {
                "type": "sequential",
                "steps": [
                    {"agent": "response_agent", "instruction": "test"}
                ]
            }
            
            test_context = {
                "text": "health check test",
                "request_id": "health_check",
                "session_id": "test_session"
            }
            
            # Don't actually execute, just validate
            is_valid = self._validate_plan(test_plan)
            
            return {
                "status": "healthy" if is_valid else "degraded",
                "components": {
                    "plan_validation": "healthy" if is_valid else "error",
                    "agent_registry": f"{len(self.agents)} agents loaded",
                    "session_manager": "connected"
                },
                "stats": self.get_execution_stats()
            }
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "stats": self.get_execution_stats()
            }

    async def cleanup(self):
        """Cleanup resources"""
        # Cancel any pending tasks, close connections, etc.
        logger.info("PlanExecutor cleanup completed")