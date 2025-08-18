from .base_agent import BaseAgent
from core.sessionManager import SessionManager, PendingMemory, ConversationState
from services.storage_service import StorageService
from langchain.embeddings import HuggingFaceEmbeddings
from google.cloud import language_v1
import google.generativeai as genai
import faiss
from typing import Any, Dict, Optional, Any, List
from datetime import datetime, timedelta
import logging
import uuid
import json
import numpy as np
import pickle
import os
from dotenv import load_dotenv
load_dotenv()


os.environ["GOOGLE_API_KEY"]= os.getenv("GOOGLE_API_KEY")
logger = logging.getLogger(__name__)

class MemoryAgent(BaseAgent):
    def __init__(self, session_manager: SessionManager, storage_service: StorageService):
        super().__init__(name="MemoryAgent")
        self.session_manager = session_manager
        self.storage = storage_service

        self.gemini_model = genai.GenerativeModel('gemini-1.5-flash')

        # Initialize embedding model
        # Free embedding model - Sentence Transformers
        try:
            # This model is free and runs locally
            self.embedding_model = HuggingFaceEmbeddings(model_name='all-MiniLM-L6-v2')  # Fast, good quality, free
            logger.info("Sentence Transformer embedding model loaded")
        except Exception as e:
            logger.warning(f"Failed to load Sentence Transformer: {e}")
            self.embedding_model = None
        
        self.embedding_dim = 384  # all-MiniLM-L6-v2 dimension

        # Initialize Google Cloud Language client
        try:
            self.language_client = language_v1.LanguageServiceClient()
            logger.info("Google Cloud Language client initialized")
        except Exception as e:
            logger.warning(f"Google Cloud Language client failed: {e}")
            self.language_client = None
        
        
        # Initialize FAISS index
        try:
            # Get embedding dimension from the model
            test_embedding = self.embedding_model.embed_query("test")
            embedding_dim = len(test_embedding)
            
            # Initialize FAISS index
            self.vector_index = faiss.IndexFlatIP(embedding_dim)  # Inner product for cosine similarity
            #self.memory_ids = []  # Track which memory corresponds to which vector
            
            logger.info(f"FAISS index initialized with dimension {embedding_dim}")
            
        except Exception as e:
            logger.error(f"Failed to initialize FAISS: {e}")
        
        self.vector_index = None
        self.memory_ids = []
        self.memory_metadata = []  # Store memory metadata parallel to FAISS index

        # Duplicate detection settings
        self.duplicate_threshold = 0.95  # High similarity threshold for duplicates
        self.time_window_minutes = 5     # Consider duplicates within 5 minutes

        # Memory confidence thresholds
        self.MIN_CONFIDENCE_FOR_STORAGE = 0.6
        self.HIGH_CONFIDENCE_THRESHOLD = 0.8
        
        # Initialize FAISS indexes per user (for session isolation)
        self.user_indexes = {}  # user_id -> {"index": faiss_index, "memory_ids": []}

        #self._load_existing_memories()
        # Load existing memories from storage
        self.user_memory_cache = {}  # user_id -> {memory_id: memory_data}
        self.cache_expiry = {}       # user_id -> expiry_time
        self.cache_duration = 300    # 5 minutes

        # Initialize memory storage dictionaries
        self.memories = {}  # Global memory storage for backward compatibility

        # Load initial memory count for logging
        self._initial_memory_count = 0

        self.logger.info(f"Memory agent initialized with {len(self.memory_metadata)} existing memories")

    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main process method implementing BaseAgent interface
        
        Routes to appropriate memory operation based on request type
        """

        try:
            instruction = input_data.get("instruction" , "process")
            session_id = input_data.get("session_id")
            user_text = input_data.get("text", "")
            explicit_memory_complete = input_data.get("explicit_memory_complete", False)

            logger.info(f"MemoryAgent processing: {instruction}")

            # Validate session
            if not session_id:
                return self._create_response({"error": "Session ID required"}, status="error")
            
            session = await self.session_manager.get_session(session_id)
            if not session:
                return self._create_response({"error": "Invalid session"}, status="error")
            
            # CHANGED: Ensure user memories are loaded (with caching)
            await self._ensure_user_memories_loaded(session.user_id)

            #if the explicit complete_memory flag is set, we assume the user wants to complete the memory
            if explicit_memory_complete and instruction != "Search existing memories":
                if session.pending_memory:
                    # Complete existing pending memory
                    return await self._complete_memory(input_data, session)
                else:
                    # No pending memory, but user wants to complete - this could be a single complete message
                    # Start and immediately complete
                    memory_result = await self._start_memory_building(input_data, session)
                    if memory_result.get("status") == "success":
                        return await self._complete_memory(input_data, session)
                    else:
                        return self._create_response({"error": f"Error creating memory for {user_text}"}, status="error")
                #return await self._complete_memory(input_data, session)

            if instruction == "Start new memory building process":
                return await self._start_memory_building(input_data, session)
            elif instruction == "Continue building existing memory":
                return await self._continue_memory_building(input_data, session)
            elif instruction == "Complete and save memory":
                return await self._complete_memory(input_data, session)
            elif instruction == "Search existing memories":
                return await self._search_memories(input_data, session)
            else:
                return self._create_response({"error": f"Unknown instruction: {instruction}"}, status="error")


        except Exception as e:
            logger.error(f"MemoryAgent error: {e}")
            return self._handle_error(e)
    
    async def _start_memory_building(self, input_data: Dict[str, Any], session) -> Dict[str, Any]:
        """
        Start building a new memory using AI to extract initial structure
        """
        user_text = input_data.get("text", "")
        session_id = session.session_id
        user_id = session.user_id
        
        logger.info(f"Starting memory building for user {user_id}: '{user_text[:50]}...'")
        
        # Step 1: Extract entities using AI
        entities = await self._extract_entities_with_ai(user_text)
        
        # Step 2: Classify memory type and generate structure using Gemini
        #memory_classification = await self._classify_memory_type_gemini(user_text, entities)
        memory_structure = await self._generate_memory_structure_gemini(
            user_text, entities
        )
        
        # Step 3: Generate embeddings for semantic search
        embeddings = await self._generate_embeddings_free(user_text)
        
        # Step 4: Analyze completeness and generate follow-up questions
        completeness_analysis = await self._analyze_memory_completeness_gemini(
            memory_structure
        )
        
        # Step 5: Process any attached media (photos, etc.)
        #media_analysis = await self._process_media_attachments(input_data)
        
        # Step 6: Create pending memory in session with rich context
        context = {
            "ai_structure": memory_structure,
            #"embeddings": embeddings.tolist() if embeddings is not None else [],
            "embeddings": embeddings.tolist() if embeddings is not None and hasattr(embeddings, 'tolist') else (embeddings if embeddings is not None else []),
            "completeness": completeness_analysis,
            "media_analysis": None,#media_analysis,
            "ai_enhanced": True,
            "ai_provider": "gemini",
            "creation_timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "initial_confidence": completeness_analysis.get("score", 0.3)
        }
        
        # Enhanced entities with media information
        # if media_analysis:
        #     entities.update(media_analysis.get("entities", {}))
        
        pending_memory = await self.session_manager.start_memory_building(
            session_id,
            user_text,
            entities,
            context
        )
        
        # Generate intelligent follow-up questions
        follow_up_questions = completeness_analysis.get("questions", [])
        needs_more_details = completeness_analysis.get("score", 0.0) < self.HIGH_CONFIDENCE_THRESHOLD
        
        result_data = {
            "action": "memory_started",
            "memory_id": pending_memory.id if pending_memory else None,
            "content_preview": user_text[:100] + "..." if len(user_text) > 100 else user_text,
            #"memory_type": memory_classification.get("type", "general"),
            "confidence_score": completeness_analysis.get("score", 0.0),
            "entities_found": entities,
            "ai_structure": memory_structure,
            "suggested_questions": follow_up_questions[:2],  # Limit to 2 questions initially
            "needs_more_details": needs_more_details,
            "media_processed": False,#bool(media_analysis),
            "ai_provider": "gemini",
            "session_state": "building_memory"
        }
        
        # Add media analysis results if available
        # if media_analysis:
        #     result_data["media_insights"] = media_analysis.get("insights", [])
        #     result_data["visual_context"] = media_analysis.get("visual_context", {})
        
        return self._create_response(result_data)
    

    async def _continue_memory_building(self, input_data: Dict[str, Any], session) -> Dict[str, Any]:
        """
        Continue building memory with enhanced AI-powered content merging
        """
        user_text = input_data.get("text", "")
        session_id = session.session_id
        
        if not session.pending_memory:
            return self._create_response({"error": "No pending memory found"}, status="error")
        
        # Extract new entities from additional input
        new_entities = await self._extract_entities_with_ai(user_text)
        
        # Process any new media attachments
        #media
        #new_media_analysis = await self._process_media_attachments(input_data)
        
        # Use Gemini to intelligently merge new information
        enhanced_content = await self._merge_memory_content_gemini(
            session.pending_memory.content,
            user_text,
            session.pending_memory.entities,
            new_entities
            #session.pending_memory.context.get("memory_type", {})
        )
        
        # Update embeddings with new content
        updated_embeddings = await self._generate_embeddings_free(enhanced_content)
        
        # Merge entities intelligently
        merged_entities = self._merge_entities(session.pending_memory.entities, new_entities)
        
        #media
        # if new_media_analysis:
        #     merged_entities.update(new_media_analysis.get("entities", {}))
        
        # Update pending memory context
        updated_context = session.pending_memory.context.copy()
        if updated_embeddings is not None:
            updated_context["embeddings"] = updated_embeddings
        
        #media
        # if new_media_analysis:
        #     existing_media = updated_context.get("media_analysis", {})
        #     updated_context["media_analysis"] = self._merge_media_analysis(existing_media, new_media_analysis)
        
        # Update memory with AI enhancement
        pending_memory = await self.session_manager.update_pending_memory(
            session_id, 
            enhanced_content,
            confidence_boost=0.2,
            new_entities=merged_entities
        )
        
        # Re-analyze completeness with updated content
        memory_structure = await self._generate_memory_structure_gemini(
            enhanced_content, merged_entities
        )
        completeness_analysis = await self._analyze_memory_completeness_gemini(
            memory_structure
        )
        
        # Track follow-up questions asked to avoid repetition
        questions_asked = updated_context.get("questions_asked", [])
        new_questions = [q for q in completeness_analysis.get("questions", []) 
                        if q not in questions_asked]
        
        result_data = {
            "action": "memory_continued",
            "memory_id": pending_memory.id if pending_memory else None,
            "enhanced_content": enhanced_content,
            "new_entities": new_entities,
            "confidence": pending_memory.confidence_score if pending_memory else 0.0,
            "completeness_score": completeness_analysis.get("score", 0.0),
            "suggested_questions": new_questions[:1],  # One question at a time for continuation
            "questions_remaining": len(new_questions),
            "ai_enhanced": True,
            "content_preview": enhanced_content[:150] + "..." if len(enhanced_content) > 150 else enhanced_content
        }
        
        #media
        # if new_media_analysis:
        #     result_data["new_media_insights"] = new_media_analysis.get("insights", [])
        
        return self._create_response(result_data)

    async def _complete_memory(self, input_data: Dict[str, Any], session) -> Dict[str, Any]:
        """
        Complete memory with final AI enrichment and permanent storage
        """
        session_id = session.session_id
        user_id = session.user_id
        
        if not session.pending_memory:
            return self._create_response({"error": "No pending memory to complete"}, status="error")
        
        # Final AI enrichment using Gemini
        enriched_memory = await self._enrich_memory_for_storage_gemini(session.pending_memory)
        
        # Generate final embeddings using free model
        final_embeddings = await self._generate_embeddings_free(enriched_memory["final_content"])
        
        # Extract action items using Gemini
        action_items = await self._extract_action_items_gemini(enriched_memory["final_content"])
        
        # Generate semantic tags for better categorization
        semantic_tags = await self._generate_semantic_tags_gemini(
            enriched_memory["final_content"], 
            enriched_memory.get("entities", {})
        )
        
        # Prepare final memory data for storage
        final_memory_data = {
            "id": session.pending_memory.id,
            "user_id": user_id,
            "content": enriched_memory["final_content"],
            "title": enriched_memory.get("title", ""),
            #"memory_type": enriched_memory.get("memory_type", "general"),
            "entities": enriched_memory.get("entities", {}),
            "confidence_score": enriched_memory.get("confidence", 0.0),
            "action_items": action_items,
            "semantic_tags": semantic_tags,
            "ai_metadata": {
                "provider": "gemini",
                "enhancement_applied": True,
                "processing_timestamp": datetime.now().isoformat(),
                "entity_extraction_method": "google_cloud_nlp" if self.language_client else "None",
                "embedding_model": "sentence-transformers/all-MiniLM-L6-v2" if self.embedding_model else "none"
            },
            "created_at": datetime.now().isoformat(),
            "session_context": {
                "session_id": session_id,
                "conversation_turns": len(session.conversation_history),
                #"media_attachments": bool(session.pending_memory.context.get("media_analysis"))
            }
        }
        
        # # Store embeddings separately for efficient vector search
        # if final_embeddings is not None:
        #     await self.storage.store_embedding(
        #         session.pending_memory.id,
        #         final_embeddings.tolist(),
        #         {
        #             "user_id": user_id,
        #             "memory_type": enriched_memory.get("memory_type", "general"),
        #             "semantic_tags": semantic_tags,
        #             "content_preview": enriched_memory["final_content"][:200]
        #         }
        #     )
        
        # # Store memory permanently
        # memory_id = await self.storage.store_memory(final_memory_data)

        # # Add to user's FAISS index
        # user_index_data = self._get_or_create_user_index(user_id)

        # # Normalize embedding for cosine similarity
        # norm_embedding = final_embeddings / np.linalg.norm(final_embeddings)
        # user_index_data["index"].add(norm_embedding.reshape(1, -1))
        # user_index_data["memory_ids"].append(memory_id)

        # Store memory and embeddings
        try:
            memory_id = await self.storage.store_memory(final_memory_data)
            
            if final_embeddings is not None:
                await self.storage.store_embedding(
                    memory_id,
                    final_embeddings,
                    {
                        "user_id": user_id,
                        "memory_type": enriched_memory.get("memory_type", "general"),
                        "semantic_tags": semantic_tags,
                        "content_preview": enriched_memory["final_content"][:200]
                    }
                )
                
                # # Add to user's FAISS index
                # user_index_data = self._get_or_create_user_index(user_id)
                # norm_embedding = final_embeddings / np.linalg.norm(final_embeddings)
                # user_index_data["index"].add(norm_embedding.reshape(1, -1))
                # user_index_data["memory_ids"].append(memory_id)
                # CRITICAL: Update cache immediately after storage

            await self._update_user_cache(user_id, memory_id, final_memory_data, final_embeddings)
            
            # Store in memory for quick access
            # self.memories[memory_id] = final_memory_data
            
        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            return self._create_response({"error": f"Storage failed: {str(e)}"}, status="error")
        
        
        # Complete memory in session
        completed_memory = await self.session_manager.complete_memory(session_id)
        
        logger.info(f"Memory {memory_id} completed and stored for user {user_id}")
        
        return self._create_response({
            "action": "memory_completed",
            "memory_id": memory_id,
            "title": enriched_memory.get("title", ""),
            "final_content": enriched_memory["final_content"],
            #"memory_type": enriched_memory.get("memory_type", "general"),
            "confidence": enriched_memory.get("confidence", 0.0),
            "entities": enriched_memory.get("entities", {}),
            "action_items": action_items,
            "semantic_tags": semantic_tags,
            "ai_enhanced": True,
            "ai_provider": "gemini",
            "storage_location": f"memories.events.{memory_id}",
            "embeddings_stored": final_embeddings is not None,
            "completed_memory": completed_memory if completed_memory else None,
            "cache_updated": True  # Indicate cache was updated
        })

    async def _search_memories(self, input_data: Dict[str, Any], session) -> Dict[str, Any]:
        "vector-embeddings based search"
        
        query_text = input_data.get("text", "")
        session_id = session.session_id
        user_id = session.user_id
        similarity_threshold = 0.15 # Lowered threshold
        k = 5

        if not query_text:
            return self._create_response({"error": "No search query provided"}, status="error")
        
        # Ensure memories are loaded
        await self._ensure_user_memories_loaded(user_id)

        # Check if user has any cached memories
        user_memories = self.user_memory_cache.get(user_id, {})
        if not user_memories:
            return self._create_response({
                "action": "memory_searched",
                "query": query_text,
                "results": [],
                "total_found": 0,
                "message": "No memories stored yet for this user.",
                "search_method": "faiss_vector_similarity"
            })
        
        # Get user's FAISS index
        user_index_data = self.user_indexes.get(user_id)
        if not user_index_data or len(user_index_data["memory_ids"]) == 0:
            return self._create_response({
                "action": "memory_searched",
                "query": query_text,
                "results": [],
                "total_found": 0,
                "message": "No searchable memories found for this user.",
                "search_method": "faiss_vector_similarity"
            })
        
        
        # Generate query embedding
        try:
            query_embedding = self.embedding_model.embed_query(query_text)
            
            # Convert to numpy array if needed
            if isinstance(query_embedding, list):
                query_embedding = np.array(query_embedding)
                
            norm_query = query_embedding / np.linalg.norm(query_embedding)
            
        except Exception as e:
            logger.error(f"Failed to generate query embedding: {e}")
            return self._create_response({"error": f"Embedding generation failed: {str(e)}"}, status="error")

        # # Search FAISS index
        # if self.vector_index is None or len(self.memory_ids) == 0:
        #     return self._create_response({
        #         "action": "memory_searched",
        #         "query": query_text,
        #         "results": [],
        #         "total_found": 0,
        #         "message": "No memories stored yet. This appears to be your first interaction.",
        #         "search_method": "faiss_vector_similarity"
        #     })

        # Perform similarity search
        # scores, indices = self.vector_index.search(norm_query.reshape(1, -1), min(k, len(self.memory_ids)))
        scores, indices = user_index_data["index"].search(
            norm_query.reshape(1, -1), 
            min(k, len(user_index_data["memory_ids"]))
        )

        # Format results with similarity threshold filtering
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and score >= similarity_threshold:  # Valid index and meets threshold:  # Valid index
                memory_id = user_index_data["memory_ids"][idx]
                memory = user_memories.get(memory_id)
                
                if memory:
                    results.append({
                        "memory_id": memory_id,
                        "content": memory.get('content', ''),
                        "title": memory.get('title', ''),
                        "similarity_score": float(score),
                        "created_at": memory.get('created_at', ''),
                        "preview": (memory.get('content', '')[:150] + "...") if len(memory.get('content', '')) > 150 else memory.get('content', '')
                    })
        
        # Handle case when no relevant memories are found
        if not results:
            return self._create_response({
                "action": "memory_searched",
                "query": query_text,
                "results": [],
                "total_found": 0,
                "message": f"No relevant memories found for '{query_text}'. The closest matches had similarity scores below the threshold ({similarity_threshold}).",
                "search_method": "faiss_vector_similarity",
                "suggestion": "Try rephrasing your query or asking about more general topics we've discussed."
        })
        
        return self._create_response({
            "action": "memory_searched",
            "query": query_text,
            "results": results,
            "total_found": len(results),
            "search_method": "faiss_vector_similarity",
            "cached_search": True
        })


    #complex version
    async def older_search_memories(self, input_data: Dict[str, Any], session) -> Dict[str, Any]:
        """
        AI-powered semantic memory search with hybrid approach
        """
        query_text = input_data.get("text", "")
        user_id = session.user_id
        
        # Generate embeddings for search query
        query_embeddings = await self._generate_embeddings_free(query_text)
        
        # Extract entities from query for structured search
        query_entities = await self._extract_entities_with_ai(query_text)
        
        # Perform hybrid search (semantic + entity-based + keyword)
        search_results = await self._hybrid_memory_search(
            query_text, 
            query_embeddings, 
            query_entities, 
            user_id
        )
        
        # Use Gemini to rank and contextualize results
        ranked_results = await self._rank_search_results_gemini(query_text, search_results)
        
        # Generate search insights using AI
        search_insights = await self._generate_search_insights_gemini(query_text, ranked_results)
        
        return self._create_response({
            "action": "memory_searched",
            "query": query_text,
            "results": ranked_results,
            "total_found": len(search_results),
            "query_entities": query_entities,
            "search_insights": search_insights,
            "search_type": "gemini_hybrid_semantic",
            "ai_provider": "gemini",
            "has_embeddings": query_embeddings is not None
        })

    # Utility Methods

    async def _extract_entities_with_ai(self, text: str) -> Dict[str, List]:
        """
        Extract entities using Google Cloud Natural Language API with fallback
        """
        if self.language_client:
            try:
                document = language_v1.Document(content=text, type_=language_v1.Document.Type.PLAIN_TEXT)
                response = self.language_client.analyze_entities(
                    request={"document": document, "encoding_type": language_v1.EncodingType.UTF8}
                )
                
                entities = {
                    "people": [],
                    "organizations": [],
                    "locations": [],
                    "events": [],
                    "other": []
                }
                
                for entity in response.entities:
                    entity_info = {
                        "name": entity.name,
                        "type": entity.type_.name,
                        "salience": entity.salience,
                        "mentions": [mention.text.content for mention in entity.mentions]
                    }
                    
                    if entity.type_.name == "PERSON":
                        entities["people"].append(entity_info)
                    elif entity.type_.name == "ORGANIZATION":
                        entities["organizations"].append(entity_info)
                    elif entity.type_.name == "LOCATION":
                        entities["locations"].append(entity_info)
                    elif entity.type_.name == "EVENT":
                        entities["events"].append(entity_info)
                    else:
                        entities["other"].append(entity_info)
                
                return entities
                
            except Exception as e:
                logger.error(f"Google Cloud entity extraction failed: {e}")
        
        return {"people": [], "organizations": [], "locations": [], "events": [], "other": []}
    

    async def _generate_memory_structure_gemini(self, text: str, entities: Dict) -> Dict[str, Any]:
        """
        Use Gemini to create intelligent memory structure based on type
        """
        if not self.gemini_model:
            return {"content": text, "structure": "basic", "error": "Gemini not available"}
        
        #memory_type = classification.get("type", "conversation")
        #template = self.memory_templates.get(memory_type, self.memory_templates["conversation"])
        
        try:
            prompt = f"""
            Analyze this memory input and create a structured representation. 
            
            Text: "{text}"
            Entities: {json.dumps(entities, indent=2)}
            
            Create a JSON structure with:
            1. title: A clear, descriptive title (max 60 characters)
            2. summary: Brief one-sentence summary
            3. key_information: Main points and details
            4. context: Setting, location, circumstances
            5. relationships: Connections between people/entities
            6. importance_level: 1-5 scale
            7. missing_information: What would make this memory more complete
            8. suggested_tags: Relevant categorization tags
            
            Focus on capturing information that will be valuable for future recall and search.
            Respond with valid JSON only.
            """
            
            response = self.gemini_model.generate_content(prompt)
            response_text = self._clean_json_response(response.text)
            return json.loads(response_text)
            
        except Exception as e:
            logger.error(f"Gemini memory structure generation failed: {e}")
            return {
                "title": text[:50] + "..." if len(text) > 50 else text,
                "summary": text,
                "structure": "basic", 
                "error": str(e)
            }
    
    async def _analyze_memory_completeness_gemini(self, memory_structure: Dict) -> Dict[str, Any]:
        """
        Analyze memory completeness and generate intelligent follow-up questions
        """
        if not self.gemini_model:
            return {"score": 0.5, "questions": ["Can you provide more details?"]}
        
        # memory_type = classification.get("type", "conversation")
        # template = self.memory_templates.get(memory_type, self.memory_templates["conversation"])
        
        try:
            prompt = f"""
            Analyze this memory for completeness:
            
            Memory Structure: {json.dumps(memory_structure, indent=2)}
            
            Provide analysis as JSON:
            {{
                "score": 0.0-1.0,
                "missing_elements": ["list", "of", "missing", "key", "info"],
                "questions": ["2-3 specific follow-up questions"],
                "confidence_factors": ["what makes this reliable"],
                "completeness_reasoning": "explanation of score",
                "priority_gaps": ["most important missing information"]
            }}
            
            Questions should be conversational and help gather the next steps requried to help user.
            Consider: Context, actionable details, relationship depth, and future utility.
            """
            
            response = self.gemini_model.generate_content(prompt)
            response_text = self._clean_json_response(response.text)
            result = json.loads(response_text)
            
            # Ensure score is valid
            result["score"] = max(0.0, min(1.0, result.get("score", 0.5)))
            
            return result
            
        except Exception as e:
            logger.error(f"Gemini completeness analysis failed: {e}")
            return {
                "score": 0.5, 
                "questions": ["Can you provide more details about this?"],
                "error": str(e)
            }
    
    async def _generate_embeddings_free(self, text: str) -> Optional[np.ndarray]:
        """
        Generate embeddings using free Sentence Transformers model
        """
        if not self.embedding_model:
            logger.warning("Embedding model not available")
            return None
        
        try:
            embeddings = self.embedding_model.embed_query(text)

            # FIXED: Ensure we always return numpy array
            if isinstance(embeddings, list):
                embeddings = np.array(embeddings)

            return embeddings
            
        except Exception as e:
            logger.error(f"Free embedding generation failed: {e}")
            return None

    async def _merge_memory_content_gemini(self, existing_content: str, new_content: str, 
                                         existing_entities: Dict, new_entities: Dict) -> str:
        """
        Intelligently merge memory content while preserving context and flow
        """
        if not self.gemini_model:
            return f"{existing_content}\n\nAdditional details: {new_content}"
        
        try:
            prompt = f"""
            Merge these memory pieces into a single, coherent narrative:
            
            Existing: "{existing_content}"
            New info: "{new_content}"

            Existing entities: {json.dumps(existing_entities, indent=2)}
            New entities: {json.dumps(new_entities, indent=2)}
            
            Create a unified, well-structured memory that:
            1. Combines all information logically
            2. Maintains chronological flow where applicable
            3. Eliminates redundancy while preserving unique details
            4. Uses natural, conversational language
            5. Preserves important context and relationships
            6. Prioritizes actionable and searchable information
            
            Return only the merged content, no JSON or formatting.
            """
            
            response = self.gemini_model.generate_content(prompt)
            return response.text.strip()
            
        except Exception as e:
            logger.error(f"Gemini memory merging failed: {e}")
            return f"{existing_content}\n\nAdditional details: {new_content}"

    async def _enrich_memory_for_storage_gemini(self, pending_memory: PendingMemory) -> Dict[str, Any]:
        """
        Final enrichment before storage with title generation and categorization
        """
        if not self.gemini_model:
            return {
                "id": pending_memory.id,
                "final_content": pending_memory.content,
                "entities": pending_memory.entities,
                "confidence": pending_memory.confidence_score,
                "title": pending_memory.content[:50] + "..." if len(pending_memory.content) > 50 else pending_memory.content
            }
        
        try:
            prompt = f"""
Enrich this memory for permanent storage. PRESERVE ALL ORIGINAL DETAILS - do not add placeholders or remove information.

Content: "{pending_memory.content}"
Entities: {json.dumps(pending_memory.entities, indent=2)}
Context: {json.dumps(pending_memory.context, indent=2)}

Rules:
1. Keep ALL original information exactly as provided
2. Do NOT add placeholders like [Add details here] or [Insert information]
3. Only enhance structure and clarity while preserving facts
4. If information is missing, leave it missing - don't add suggestions
5. Focus on making existing content more searchable and organized
6. IMPORTANT: Use second person perspective (YOU/YOUR) not first person (I/WE)
- Convert "I met" → "You met"
- Convert "We discussed" → "You discussed" or "You both discussed"
- Convert "I plan" → "You plan"
- This is a memory about the USER, so use "you" perspective

Provide enrichment as JSON:
{{
    "title": "Clear, descriptive title (max 60 chars)",
    "final_content": "Polished, complete content",
    "memory_type": "meeting|conversation|event|opportunity|learning|personal",
    "importance_score": 1-5,
    "key_relationships": {{"person": "relationship_context"}},
    "actionable_insights": ["insights", "that", "enable", "future", "action"],
    "search_keywords": ["relevant", "search", "terms"],
    "confidence": 0.0-1.0
}}
            """
            
            response = self.gemini_model.generate_content(prompt)
            response_text = self._clean_json_response(response.text)
            result = json.loads(response_text)
            
            # Add original data
            result.update({
                "id": pending_memory.id,
                "entities": pending_memory.entities,
                "original_confidence": pending_memory.confidence_score
            })
            
            return result
            
        except Exception as e:
            logger.error(f"Gemini memory enrichment failed: {e}")
            return {
                "id": pending_memory.id,
                "final_content": pending_memory.content,
                "entities": pending_memory.entities,
                "confidence": pending_memory.confidence_score,
                "title": pending_memory.content[:50] + "..." if len(pending_memory.content) > 50 else pending_memory.content,
                "error": str(e)
            }

    async def _extract_action_items_gemini(self, memory_content: str) -> List[Dict[str, Any]]:
        """
        Extract actionable items from memory using Gemini
        """
        if not self.gemini_model:
            return []
        
        try:
            prompt = f"""
            Extract action items from this memory:
            
            "{memory_content}"
            
            For each action item, provide:
            {{
                "task": "specific action to take",
                "priority": "high|medium|low",
                "suggested_deadline_days": number_or_null,
                "context": "why this action is important",
                "category": "follow_up|research|schedule|contact|reminder|task"
            }}
            
            Return as JSON array. If no action items exist, return [].
            """
            
            response = self.gemini_model.generate_content(prompt)
            response_text = self._clean_json_response(response.text)
            return json.loads(response_text)
            
        except Exception as e:
            logger.error(f"Gemini action item extraction failed: {e}")
            return []

    async def _generate_semantic_tags_gemini(self, content: str, entities: Dict) -> List[str]:
        """
        Generate semantic tags for better categorization and search
        """
        if not self.gemini_model:
            # return self._handle_error("Gemini model not available for tag generation")
            logger.error("Gemini model not available for tag generation")
            return ["general", "conversation"]
        
        try:
            prompt = f"""
            Generate 5-7 semantic tags for this memory:
            
            Content: "{content}"
            Entities: {json.dumps(entities, indent=2)}
            
            Tags should be:
            - Useful for search and categorization
            - Include memory type, context, and key themes
            - Mix of general and specific terms
            - Help with future discovery
            
            Return as JSON array: ["tag1", "tag2", "tag3", ...]
            """
            
            response = self.gemini_model.generate_content(prompt)
            response_text = self._clean_json_response(response.text)
            return json.loads(response_text)
            
        except Exception as e:
            logger.error(f"Gemini tag generation failed: {e}")
            return ["general", "conversation"]

    async def _hybrid_memory_search(self, query: str, query_embeddings: np.ndarray, 
                                  query_entities: Dict, user_id: str) -> List[Dict]:
        """
        Perform hybrid search combining semantic similarity, entity matching, and keyword search
        """
        all_results = []
        
        try:
            # 1. Semantic search using embeddings
            if query_embeddings is not None:
                semantic_results = await self._semantic_search(query_embeddings, user_id)
                all_results.extend(semantic_results)
            
            # 2. Entity-based search
            entity_results = await self._entity_based_search(query_entities, user_id)
            all_results.extend(entity_results)
            
            # 3. Keyword search
            keyword_results = await self._keyword_search(query, user_id)
            all_results.extend(keyword_results)
            
            # 4. Deduplicate and combine scores
            unique_results = self._deduplicate_search_results(all_results)
            
            # 5. Sort by combined relevance score
            sorted_results = sorted(unique_results, key=lambda x: x.get("relevance_score", 0), reverse=True)
            
            return sorted_results[:20]  # Return top 20 results
            
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            return []
    
    async def _semantic_search(self, query_embeddings: np.ndarray, user_id: str) -> List[Dict]:
        """
        Perform semantic search using stored embeddings
        """
        try:
            # Get all embeddings for user's memories
            all_embeddings = await self.storage.list_embeddings()
            user_embeddings = [e for e in all_embeddings if e.get("metadata", {}).get("user_id") == user_id]
            
            if not user_embeddings:
                return []
            
            # Calculate similarities
            results = []
            for emb_data in user_embeddings:
                stored_embedding = np.array(emb_data["embedding"])
                
                # Calculate cosine similarity
                similarity = cosine_similarity(
                    query_embeddings.reshape(1, -1),
                    stored_embedding.reshape(1, -1)
                )[0][0]
                
                if similarity > 0.3:  # Threshold for relevance
                    # Get the actual memory data
                    memory = await self.storage.get_memory(emb_data["content_id"])
                    if memory:
                        results.append({
                            "memory_id": emb_data["content_id"],
                            "content": memory.get("content", ""),
                            "title": memory.get("title", ""),
                            "relevance_score": similarity,
                            "match_type": "semantic",
                            "memory_type": memory.get("memory_type", "general"),
                            "entities": memory.get("entities", {}),
                            "timestamp": memory.get("created_at", ""),
                            "embedding_similarity": similarity
                        })
            
            return results
            
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []

    async def _load_user_memories(self, user_id: str) -> Dict[str, Any]:
        """Load all memories for a user and rebuild FAISS index"""
        try:
            # Get all memories from storage service
            all_memories = await self.storage.list_memories(limit=100)  # Adjust limit as needed
            
            # Filter memories for this user
            user_memories = [m for m in all_memories if m.get("user_id") == user_id]

            # Initialize cache for this user
            self.user_memory_cache[user_id] = {}
            
            if not user_memories:
                return self._create_response({
                    "action": "user_memories_loaded",
                    "user_id": user_id,
                    "memories_loaded": 0,
                    "message": "No memories found for this user"
                })
            
            # Create fresh FAISS index for user
            user_index_data = self._get_or_create_user_index(user_id)
            user_index_data["index"] = faiss.IndexFlatIP(self.embedding_dim)
            user_index_data["memory_ids"] = []
            
            # Load embeddings and rebuild index
            loaded_count = 0
            for memory in user_memories:
                memory_id = memory["id"]

                # Add to cache
                self.user_memory_cache[user_id][memory_id] = memory

                # Also add to global memories dict for backward compatibility
                self.memories[memory_id] = memory
                
                # Get embedding from storage service
                embedding_data = await self.storage.get_embedding(memory_id)
                
                if embedding_data and embedding_data.get("embedding"):
                    embedding = np.array(embedding_data["embedding"])
                    
                    # Add to FAISS index
                    norm_embedding = embedding / np.linalg.norm(embedding)
                    user_index_data["index"].add(norm_embedding.reshape(1, -1))
                    user_index_data["memory_ids"].append(memory_id)
                    loaded_count += 1
                else:
                    logger.warning(f"No embedding found for memory {memory_id}")
            
            return self._create_response({
                "action": "user_memories_loaded",
                "user_id": user_id,
                "memories_loaded": loaded_count,
                "total_memories": len(user_memories),
                "faiss_index_ready": True
            })
            
        except Exception as e:
            logger.error(f"Failed to load user memories: {e}")
            # Initialize empty cache on error
            self.user_memory_cache[user_id] = {}
            return self._create_response({"error": f"Failed to load memories: {str(e)}"}, status="error")

    # ADD: Lazy loading with caching
    async def _ensure_user_memories_loaded(self, user_id: str) -> bool:
        """Load user memories only if not cached or expired"""
        current_time = datetime.now()
        
        # Check if already cached and not expired
        if (user_id in self.user_memory_cache and 
            user_id in self.cache_expiry and 
            current_time < self.cache_expiry[user_id]):
            logger.debug(f"Using cached memories for user {user_id}")
            return True
        
        # Load memories for this user
        logger.info(f"Loading memories for user {user_id}")
        await self._load_user_memories(user_id)
        self.cache_expiry[user_id] = current_time + timedelta(seconds=self.cache_duration)
        return True
    
    async def _update_user_cache(self, user_id: str, memory_id: str, 
                               memory_data: Dict, embeddings: np.ndarray = None):
        """Update user's memory cache and FAISS index immediately"""
        
        # Initialize cache if doesn't exist
        if user_id not in self.user_memory_cache:
            self.user_memory_cache[user_id] = {}
        
        # Add memory to cache
        self.user_memory_cache[user_id][memory_id] = memory_data
        
        # Also update global memories dict for backward compatibility
        self.memories[memory_id] = memory_data
        
        # Update FAISS index
        if embeddings is not None:
            # FIXED: Ensure embeddings is numpy array
            if isinstance(embeddings, list):
                embeddings = np.array(embeddings)
            user_index_data = self._get_or_create_user_index(user_id)
            norm_embedding = embeddings / np.linalg.norm(embeddings)
            user_index_data["index"].add(norm_embedding.reshape(1, -1))
            user_index_data["memory_ids"].append(memory_id)
        
        # Refresh cache expiry
        self.cache_expiry[user_id] = datetime.now() + timedelta(seconds=self.cache_duration)
        
        logger.info(f"Updated cache for user {user_id}: added memory {memory_id}")

    def _get_or_create_user_index(self, user_id: str) -> Dict:
        """Get or create FAISS index for a specific user"""
        if user_id not in self.user_indexes:
            # Create new FAISS index for this user
            index = faiss.IndexFlatIP(self.embedding_dim)  # Cosine similarity
            self.user_indexes[user_id] = {
                "index": index,
                "memory_ids": []
            }
            logger.info(f"Created new FAISS index for user: {user_id}")
        
        return self.user_indexes[user_id]
    
    def _merge_entities(self, existing: Dict, new: Dict) -> Dict:
        """
        Intelligently merge entity dictionaries
        """
        merged = existing.copy()
        
        for entity_type, new_entities in new.items():
            if entity_type not in merged:
                merged[entity_type] = []
            
            # Add new entities, avoiding duplicates
            existing_names = {
                e.get("name", "").lower() if isinstance(e, dict) else str(e).lower() 
                for e in merged[entity_type]
            }
            
            for new_entity in new_entities:
                new_name = new_entity.get("name", "").lower() if isinstance(new_entity, dict) else str(new_entity).lower()
                
                if new_name not in existing_names:
                    merged[entity_type].append(new_entity)
                    existing_names.add(new_name)
        
        return merged
    

    
    def _clean_json_response(self, response_text: str) -> str:
        """
        Clean Gemini response text to extract valid JSON
        """
        response_text = response_text.strip()
        
        # Remove code block markers
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        elif response_text.startswith('```'):
            response_text = response_text[3:]
        
        if response_text.endswith('```'):
            response_text = response_text[:-3]
        
        return response_text.strip()
    

    # ADD: Cache management methods
    async def invalidate_user_cache(self, user_id: str):
        """Invalidate cache for a specific user"""
        if user_id in self.user_memory_cache:
            del self.user_memory_cache[user_id]
        if user_id in self.cache_expiry:
            del self.cache_expiry[user_id]
        logger.info(f"Cache invalidated for user {user_id}")

    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for monitoring"""
        current_time = datetime.now()
        
        stats = {
            "total_cached_users": len(self.user_memory_cache),
            "total_cached_memories": sum(len(memories) for memories in self.user_memory_cache.values()),
            "cache_hit_rate": "not_implemented",  # Implement if needed
            "expired_caches": 0,
            "active_caches": 0
        }
        
        for user_id, expiry_time in self.cache_expiry.items():
            if current_time > expiry_time:
                stats["expired_caches"] += 1
            else:
                stats["active_caches"] += 1
        
        return stats

    # ADD: Method to clean up expired caches (optional background task)
    async def cleanup_expired_caches(self):
        """Clean up expired caches to free memory"""
        current_time = datetime.now()
        expired_users = []
        
        for user_id, expiry_time in self.cache_expiry.items():
            if current_time > expiry_time:
                expired_users.append(user_id)
        
        for user_id in expired_users:
            await self.invalidate_user_cache(user_id)
        
        if expired_users:
            logger.info(f"Cleaned up {len(expired_users)} expired caches")

    

    # Add these debugging methods to your MemoryAgent class

    async def debug_embedding_similarity(self, query: str, user_id: str) -> Dict[str, Any]:
        """Debug embedding similarity calculation step by step"""
        
        if not self.embedding_model:
            return {"error": "Embedding model not available"}
        
        # Ensure memories are loaded
        await self._ensure_user_memories_loaded(user_id)
        
        debug_info = {
            "query": query,
            "user_id": user_id,
            "embedding_analysis": {},
            "similarity_breakdown": []
        }
        
        # Generate query embedding
        try:
            query_embedding = self.embedding_model.embed_query(query)

            # FIXED: Convert to numpy array if it's a list
            if isinstance(query_embedding, list):   
                query_embedding = np.array(query_embedding)

            query_norm = np.linalg.norm(query_embedding)
            norm_query = query_embedding / query_norm
            
            debug_info["embedding_analysis"]["query"] = {
                "embedding_shape": np.array(query_embedding).shape,
                "embedding_norm": float(query_norm),
                "first_10_values": query_embedding[:10].tolist()
            }
            
        except Exception as e:
            return {"error": f"Failed to generate query embedding: {e}"}
        
        # Get user memories and their embeddings
        user_memories = self.user_memory_cache.get(user_id, {})
        
        if not user_memories:
            return {"error": "No cached memories found"}
        
        # Analyze each memory's similarity
        for memory_id, memory_data in user_memories.items():
            memory_content = memory_data.get('content', '')
            memory_title = memory_data.get('title', '')
            
            try:
                # Generate embedding for this memory content
                memory_embedding = self.embedding_model.embed_query(memory_content)
                memory_norm = np.linalg.norm(memory_embedding)
                norm_memory = memory_embedding / memory_norm
                
                # Calculate cosine similarity manually
                cosine_sim = np.dot(norm_query, norm_memory)
                
                # Also test different parts of the memory
                title_embedding = self.embedding_model.embed_query(memory_title)
                title_norm = np.linalg.norm(title_embedding)
                norm_title = title_embedding / title_norm
                title_similarity = np.dot(norm_query, norm_title)
                
                # Test key phrases from memory
                entities_text = " ".join([
                    " ".join([entity.get('name', '') for entity in entities]) 
                    for entities in memory_data.get('entities', {}).values()
                ])
                
                entity_similarity = 0.0
                if entities_text.strip():
                    entity_embedding = self.embedding_model.embed_query(entities_text)
                    entity_norm = np.linalg.norm(entity_embedding)
                    norm_entity = entity_embedding / entity_norm
                    entity_similarity = np.dot(norm_query, norm_entity)
                
                debug_info["similarity_breakdown"].append({
                    "memory_id": memory_id,
                    "memory_title": memory_title,
                    "content_preview": memory_content[:200] + "...",
                    "content_similarity": float(cosine_sim),
                    "title_similarity": float(title_similarity),
                    "entity_similarity": float(entity_similarity),
                    "memory_embedding_norm": float(memory_norm),
                    "embedding_first_10": memory_embedding[:10].tolist(),
                    "passes_threshold": cosine_sim >= 0.3,
                    "semantic_tags": memory_data.get('semantic_tags', [])
                })
                
            except Exception as e:
                debug_info["similarity_breakdown"].append({
                    "memory_id": memory_id,
                    "error": f"Failed to analyze: {e}",
                    "memory_title": memory_title,
                    "content_preview": memory_content[:100] + "..."
                })
        
        # Sort by similarity
        debug_info["similarity_breakdown"].sort(
            key=lambda x: x.get("content_similarity", 0), 
            reverse=True
        )
        
        return debug_info

    async def test_different_queries(self, user_id: str) -> Dict[str, Any]:
        """Test different query formulations for the Jennifer Chen memory"""
        
        test_queries = [
            "Hello, can you help me remember whom I met at conference?",
            "Who did I meet at the conference?",
            "Jennifer Chen",
            "Stripe",
            "conference networking",
            "VP of Engineering",
            "hiring senior engineers",
            "payment APIs",
            "business card contact",
            "job opportunity Stripe",
            "conference August 2025"
        ]
        
        results = {
            "user_id": user_id,
            "test_results": []
        }
        
        for query in test_queries:
            try:
                # Simulate the search process
                query_embedding = self.embedding_model.embed_query(query)
                norm_query = query_embedding / np.linalg.norm(query_embedding)
                
                user_memories = self.user_memory_cache.get(user_id, {})
                best_match = None
                best_score = 0.0
                
                for memory_id, memory_data in user_memories.items():
                    memory_content = memory_data.get('content', '')
                    memory_embedding = self.embedding_model.embed_query(memory_content)
                    norm_memory = memory_embedding / np.linalg.norm(memory_embedding)
                    
                    similarity = np.dot(norm_query, norm_memory)
                    
                    if similarity > best_score:
                        best_score = similarity
                        best_match = {
                            "memory_id": memory_id,
                            "title": memory_data.get('title', ''),
                            "similarity": float(similarity)
                        }
                
                results["test_results"].append({
                    "query": query,
                    "best_match": best_match,
                    "passes_threshold": best_score >= 0.3
                })
                
            except Exception as e:
                results["test_results"].append({
                    "query": query,
                    "error": str(e)
                })
        
        return results

    async def analyze_memory_content_for_search(self, memory_id: str) -> Dict[str, Any]:
        """Analyze how well a memory is structured for search"""
        
        try:
            # Find the memory in any user's cache
            memory_data = None
            found_user_id = None
            
            for user_id, user_memories in self.user_memory_cache.items():
                if memory_id in user_memories:
                    memory_data = user_memories[memory_id]
                    found_user_id = user_id
                    break
            
            if not memory_data:
                return {"error": f"Memory {memory_id} not found in cache"}
            
            content = memory_data.get('content', '')
            title = memory_data.get('title', '')
            entities = memory_data.get('entities', {})
            
            # Generate embeddings for different parts
            content_embedding = self.embedding_model.embed_query(content)
            title_embedding = self.embedding_model.embed_query(title)
            
            # Extract key phrases
            key_phrases = []
            for entity_type, entity_list in entities.items():
                for entity in entity_list:
                    if isinstance(entity, dict):
                        key_phrases.append(entity.get('name', ''))
                    else:
                        key_phrases.append(str(entity))
            
            # Test different search scenarios
            search_scenarios = [
                ("conference", "Direct keyword match"),
                ("who did I meet", "Question about people"),
                ("networking event", "Event type description"),
                ("Jennifer Chen", "Person's name"),
                ("Stripe hiring", "Company + context"),
                ("VP Engineering", "Job title"),
                ("payment APIs", "Technical topic"),
                ("contact information", "Contact details")
            ]
            
            scenario_results = []
            for scenario, description in search_scenarios:
                scenario_embedding = self.embedding_model.embed_query(scenario)
                content_sim = np.dot(
                    content_embedding / np.linalg.norm(content_embedding),
                    scenario_embedding / np.linalg.norm(scenario_embedding)
                )
                title_sim = np.dot(
                    title_embedding / np.linalg.norm(title_embedding),
                    scenario_embedding / np.linalg.norm(scenario_embedding)
                )
                
                scenario_results.append({
                    "scenario": scenario,
                    "description": description,
                    "content_similarity": float(content_sim),
                    "title_similarity": float(title_sim),
                    "would_find": content_sim >= 0.3 or title_sim >= 0.3
                })
            
            return {
                "memory_id": memory_id,
                "user_id": found_user_id,
                "analysis": {
                    "content_length": len(content),
                    "title": title,
                    "key_entities": key_phrases,
                    "semantic_tags": memory_data.get('semantic_tags', [])
                },
                "search_scenarios": scenario_results,
                "recommendations": self._generate_search_optimization_recommendations(
                    content, title, entities, scenario_results
                )
            }
            
        except Exception as e:
            return {"error": f"Analysis failed: {e}"}

    def _generate_search_optimization_recommendations(self, content: str, title: str, 
                                                    entities: Dict, scenario_results: List) -> List[str]:
        """Generate recommendations for better search optimization"""
        
        recommendations = []
        
        # Check if any scenarios passed
        passing_scenarios = [s for s in scenario_results if s["would_find"]]
        
        if len(passing_scenarios) < 3:
            recommendations.append("Content may be too formal/structured - consider adding more conversational phrases")
        
        # Check for person names in title
        people = entities.get('people', [])
        if people and not any(person.get('name', '') in title for person in people):
            recommendations.append("Consider including person names in the title for better name-based searches")
        
        # Check for event context
        if 'conference' in content.lower() and not any('event' in tag.lower() for tag in entities.get('semantic_tags', [])):
            recommendations.append("Add event-related semantic tags")
        
        # Check content structure
        if len(content.split('.')) < 3:
            recommendations.append("Content might benefit from more detailed context and background")
        
        return recommendations
   
    # Add this method to your MemoryAgent class

    async def _enhance_search_query(self, original_query: str) -> List[str]:
        """Generate multiple query variations for better semantic matching"""
        
        query_variations = [original_query]  # Always include original
        
        # Convert questions to statements
        if "who did i meet" in original_query.lower() or "whom i met" in original_query.lower():
            query_variations.extend([
                "met someone at conference",
                "conference networking meeting person",
                "business meeting conference contact"
            ])
        
        # Add context-specific variations
        if "conference" in original_query.lower():
            query_variations.extend([
                "networking event professional meeting",
                "business conference contact exchange",
                "conference attendee professional connection"
            ])
        
        # Add entity-based queries if we can extract them
        try:
            entities = await self._extract_entities_with_ai(original_query)
            for entity_type, entity_list in entities.items():
                for entity in entity_list:
                    if isinstance(entity, dict) and entity.get('name'):
                        query_variations.append(entity['name'])
        except:
            pass
        
        return query_variations

    async def _multi_query_search(self, input_data: Dict[str, Any], session) -> Dict[str, Any]:
        """Perform search with multiple query variations and combine results"""
        
        original_query = input_data.get("text", "")
        user_id = session.user_id
        similarity_threshold = 0.15  # Lowered threshold
        k = 5
        
        if not original_query:
            return self._create_response({"error": "No search query provided"}, status="error")
        
        # Ensure memories are loaded
        await self._ensure_user_memories_loaded(user_id)
        
        user_memories = self.user_memory_cache.get(user_id, {})
        if not user_memories:
            return self._create_response({
                "action": "memory_searched",
                "query": original_query,
                "results": [],
                "total_found": 0,
                "message": "No memories stored yet for this user."
            })
        
        # Get user's FAISS index
        user_index_data = self.user_indexes.get(user_id)
        if not user_index_data or len(user_index_data["memory_ids"]) == 0:
            return self._create_response({
                "action": "memory_searched",
                "query": original_query,
                "results": [],
                "total_found": 0,
                "message": "No searchable memories found for this user."
            })
        
        # Generate query variations
        query_variations = await self._enhance_search_query(original_query)
        
        # Search with each variation and combine results
        all_results = {}  # memory_id -> best_score
        
        for query_variant in query_variations:
            try:
                query_embedding = self.embedding_model.embed_query(query_variant)
                norm_query = query_embedding / np.linalg.norm(query_embedding)
                
                # Search FAISS index
                scores, indices = user_index_data["index"].search(
                    norm_query.reshape(1, -1), 
                    min(k, len(user_index_data["memory_ids"]))
                )
                
                # Process results
                for score, idx in zip(scores[0], indices[0]):
                    if idx >= 0 and score >= similarity_threshold:
                        memory_id = user_index_data["memory_ids"][idx]
                        # Keep the best score for each memory
                        if memory_id not in all_results or score > all_results[memory_id]["score"]:
                            all_results[memory_id] = {
                                "score": float(score),
                                "matching_query": query_variant
                            }
            except Exception as e:
                logger.warning(f"Search failed for query variant '{query_variant}': {e}")
                continue
        
        # Format final results
        results = []
        for memory_id, result_data in all_results.items():
            memory = user_memories.get(memory_id)
            if memory:
                results.append({
                    "memory_id": memory_id,
                    "content": memory.get('content', ''),
                    "title": memory.get('title', ''),
                    "similarity_score": result_data["score"],
                    "matching_query": result_data["matching_query"],
                    "created_at": memory.get('created_at', ''),
                    "preview": (memory.get('content', '')[:150] + "...") if len(memory.get('content', '')) > 150 else memory.get('content', '')
                })
        
        # Sort by similarity score
        results.sort(key=lambda x: x["similarity_score"], reverse=True)
        
        if not results:
            return self._create_response({
                "action": "memory_searched",
                "query": original_query,
                "results": [],
                "total_found": 0,
                "message": f"No relevant memories found. Tried {len(query_variations)} query variations. Consider lowering the similarity threshold or rephrasing your query.",
                "query_variations_tried": query_variations
            })
        
        return self._create_response({
            "action": "memory_searched",
            "query": original_query,
            "results": results,
            "total_found": len(results),
            "query_variations_used": len(query_variations),
            "search_method": "multi_query_faiss_similarity"
        })

    # Replace your existing _search_memories method with this:
    # async def _search_memories(self, input_data: Dict[str, Any], session) -> Dict[str, Any]:
    #     """Enhanced search with multiple strategies"""
    #     return await self._multi_query_search(input_data, session)