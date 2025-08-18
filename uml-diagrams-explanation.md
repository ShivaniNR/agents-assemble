# Agents Assemble - UML Diagrams Explanation

This document explains the UML sequence diagrams and architecture diagram created for the Agents Assemble system.

## Overview

The Agents Assemble system is designed as a multi-agent architecture that processes user input (text, voice, or images), manages conversational memory, and generates appropriate responses. The system uses a combination of specialized agents coordinated by a central planning and execution mechanism.

## System Architecture Diagram

The `system-architecture-diagram.puml` presents a high-level view of the system components and their relationships:

- **Frontend Components**: User interface elements for voice input, memory visualization, and photo uploads
- **Backend Core**: Coordinates the processing of requests, planning, and execution
- **Agents**: Specialized components for specific tasks (planning, memory management, context enrichment, vision processing, etc.)
- **Services**: Shared services for storage and AI capabilities
- **Data Storage**: Persistent storage for memories, embeddings, and session data
- **External APIs**: Integration with Google's AI services

Key relationships in the architecture:

1. The `InputProcessor` serves as the central entry point for all user requests
2. The `PlannerAgent` analyzes user intent and determines which agents are needed
3. The `PlanExecutor` orchestrates the execution of the selected agents
4. The `SessionManager` maintains conversation state and memory context
5. External services provide AI capabilities for various agents

## System Sequential Flow Diagram

The `agents-assemble-sequence-diagram.puml` illustrates the sequential flow of operations in the system:

1. **User Input Processing**:

   - The `InputProcessor` receives user input (text, audio, or images)
   - Voice input is transcribed by the `VoiceAgent`
   - The `PlannerAgent` classifies the user's intent and selects appropriate agents
   - An execution plan is created with specific instructions for each agent

2. **Plan Execution**:

   - The `PlanExecutor` manages the sequential execution of agents
   - Different agents are invoked based on the user's intent and input type
   - Memory operations are handled by the `MemoryAgent`
   - Image analysis is performed by the `VisionAgent`
   - Context enrichment is performed by the `ContextAgent`
   - The `ResponseAgent` generates the final response to the user

3. **Memory Building Process**:

   - Details the flow when a user wants to store a new memory
   - Shows the back-and-forth interaction for memory enrichment
   - Illustrates the continuation and completion phases

4. **Memory Query Process**:
   - Shows how the system retrieves memories based on user queries
   - Illustrates the embedding-based search process
   - Demonstrates how memories are transformed into natural language responses

## Memory Operations Flow Diagram

The `memory-operations-sequence-diagram.puml` provides a detailed view of the memory management operations:

1. **Memory Storage Flow**:

   - User initiates memory storage with an initial statement
   - The system extracts entities and creates a structured representation
   - Follow-up questions are generated to gather more details
   - The memory is stored in a pending state

2. **Memory Continuation Flow**:

   - User provides additional details about the memory
   - New information is merged with existing content
   - The system may ask additional questions for enrichment

3. **Memory Completion Flow**:

   - User indicates the memory is complete
   - The memory is enriched, finalized, and stored permanently
   - Embeddings are generated for future retrieval
   - The system confirms successful storage

4. **Memory Query Flow**:
   - User asks about a previously stored memory
   - The system generates embeddings for the query
   - Vector similarity search is performed to find relevant memories
   - The system responds with information from the retrieved memory

## Key Sequence Patterns

Throughout the diagrams, several key patterns are evident:

1. **Intent-driven Agent Selection**: The system analyzes user intent to determine which agents to activate.

2. **Sequential Processing Pipeline**: Input flows through a series of processing steps (classification, planning, execution, response).

3. **Stateful Conversation Management**: The `SessionManager` maintains conversation state and pending memory context.

4. **AI Enhancement at Multiple Stages**: AI models (Gemini) are used for intent classification, memory enrichment, and response generation.

5. **Vector-based Memory Retrieval**: Embeddings are used for semantic search of stored memories.

6. **Contextual Enrichment**: The `ContextAgent` adds relevant calendar and email data to enhance memories with real-world context.

## Implementation Details

The UML diagrams reflect the following implementation aspects:

1. **Agent Communication**: Agents communicate through the orchestration layer, not directly with each other.

2. **Memory Building Process**:

   - Uses a three-phase approach: start, continue, complete
   - Embeddings are generated for semantic search
   - Entity extraction enriches memory with structured data
   - Integration with calendar and email data via the `ContextAgent`

3. **Plan Execution**:

   - Supports both sequential and parallel agent execution
   - Handles agent dependencies and error conditions
   - Accumulates results from multiple agents

4. **Response Generation**:
   - Context-aware responses based on intent and memory operations
   - Follows up with appropriate questions for memory enrichment
   - Provides confirmation on successful operations

These diagrams serve as documentation of the system's architecture and behavior, helping to understand the flow of operations and interactions between components.
