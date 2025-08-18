"""
Storage Service for Life Witness Agent

This service provides a unified interface for all data persistence needs,
including memories, embeddings, files, and cache. Designed with abstraction
to easily migrate from local JSON storage to external databases later.
"""

import json
import os
import shutil
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import asyncio
import aiofiles
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Custom exception for storage-related errors"""
    pass


class BaseStorageBackend(ABC):
    """Abstract base class for storage backends"""
    
    @abstractmethod
    async def read(self, key: str) -> Optional[Dict[str, Any]]:
        """Read data by key"""
        pass
    
    @abstractmethod
    async def write(self, key: str, data: Dict[str, Any]) -> bool:
        """Write data by key"""
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete data by key"""
        pass
    
    @abstractmethod
    async def list_keys(self, prefix: str = "") -> List[str]:
        """List all keys with optional prefix filter"""
        pass


class JSONFileBackend(BaseStorageBackend):
    """Local JSON file storage backend"""
    
    def __init__(self, base_path: str = "data"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        for subdir in ["memories", "cache", "embeddings", "files"]:
            (self.base_path / subdir).mkdir(exist_ok=True)
    
    def _get_file_path(self, key: str) -> Path:
        """Convert key to file path, handling nested keys"""
        # Replace dots with path separators for nested keys
        path_parts = key.split('.')
        file_path = self.base_path / Path(*path_parts[:-1]) / f"{path_parts[-1]}.json"
        
        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        return file_path
    
    async def read(self, key: str) -> Optional[Dict[str, Any]]:
        """Read JSON data from file"""
        file_path = self._get_file_path(key)
        
        if not file_path.exists():
            return None
        
        try:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                return json.loads(content)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error reading {key}: {e}")
            raise StorageError(f"Failed to read {key}: {e}")
    
    async def write(self, key: str, data: Dict[str, Any]) -> bool:
        """Write JSON data to file"""
        file_path = self._get_file_path(key)
        
        try:
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                json_str = json.dumps(data, indent=2, ensure_ascii=False, default=str)
                await f.write(json_str)
            return True
        except (IOError, TypeError) as e:
            logger.error(f"Error writing {key}: {e}")
            raise StorageError(f"Failed to write {key}: {e}")
    
    async def delete(self, key: str) -> bool:
        """Delete file"""
        file_path = self._get_file_path(key)
        
        try:
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except IOError as e:
            logger.error(f"Error deleting {key}: {e}")
            raise StorageError(f"Failed to delete {key}: {e}")
    
    async def list_keys(self, prefix: str = "") -> List[str]:
        """List all JSON files as keys"""
        keys = []
        search_path = self.base_path
        
        if prefix:
            # Handle prefixed searches
            prefix_parts = prefix.split('.')
            search_path = self.base_path / Path(*prefix_parts)
        
        if not search_path.exists():
            return keys
        
        for json_file in search_path.rglob("*.json"):
            # Convert file path back to key format
            relative_path = json_file.relative_to(self.base_path)
            key = str(relative_path.with_suffix('')).replace(os.sep, '.')
            
            if not prefix or key.startswith(prefix):
                keys.append(key)
        
        return sorted(keys)


class StorageService:
    """
    Main storage service that provides high-level operations for the Life Witness Agent.
    
    This service handles:
    - Memory events (life experiences, interactions)
    - Vector embeddings (for semantic search)
    - File storage (photos, audio, documents)
    - Cache management (API responses, temporary data)
    """
    
    def __init__(self, backend: BaseStorageBackend = None, base_path: str = "data"):
        self.backend = backend or JSONFileBackend(base_path)
        self.base_path = Path(base_path)
        
        # Initialize file storage directory
        self.files_dir = self.base_path / "files"
        self.files_dir.mkdir(parents=True, exist_ok=True)
    
    # Memory Operations
    async def store_memory(self, memory_data: Dict[str, Any]) -> str:
        """
        Store a life memory event
        
        Args:
            memory_data: Dictionary containing memory information
            
        Returns:
            str: Unique memory ID
        """
        memory_id = memory_data.get('id') or str(uuid.uuid4())
        
        # Add metadata
        memory_data.update({
            'id': memory_id,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'version': 1
        })
        
        key = f"memories.events.{memory_id}"
        await self.backend.write(key, memory_data)
        
        logger.info(f"Stored memory: {memory_id}")
        return memory_id
    
    async def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific memory by ID"""
        key = f"memories.events.{memory_id}"
        return await self.backend.read(key)
    
    async def update_memory(self, memory_id: str, updates: Dict[str, Any]) -> bool:
        """Update an existing memory"""
        existing_memory = await self.get_memory(memory_id)
        if not existing_memory:
            return False
        
        # Merge updates
        existing_memory.update(updates)
        existing_memory['updated_at'] = datetime.now(timezone.utc).isoformat()
        existing_memory['version'] = existing_memory.get('version', 1) + 1
        
        key = f"memories.events.{memory_id}"
        await self.backend.write(key, existing_memory)
        return True
    
    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory"""
        key = f"memories.events.{memory_id}"
        return await self.backend.delete(key)
    
    async def list_memories(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List all memories with pagination"""
        keys = await self.backend.list_keys("memories.events")
        
        memories = []
        for key in keys[offset:offset + limit]:
            memory = await self.backend.read(key)
            if memory:
                memories.append(memory)
        
        # Sort by created_at (newest first)
        memories.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return memories
    
    # Embedding Operations
    async def store_embedding(self, content_id: str, embedding: List[float], metadata: Dict[str, Any] = None) -> bool:
        """Store vector embedding for semantic search"""
        embedding_data = {
            'content_id': content_id,
            'embedding': embedding,
            'metadata': metadata or {},
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        key = f"embeddings.{content_id}"
        await self.backend.write(key, embedding_data)
        return True
    
    async def get_embedding(self, content_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve embedding by content ID"""
        key = f"embeddings.{content_id}"
        return await self.backend.read(key)
    
    async def list_embeddings(self) -> List[Dict[str, Any]]:
        """List all embeddings"""
        keys = await self.backend.list_keys("embeddings")
        
        embeddings = []
        for key in keys:
            embedding = await self.backend.read(key)
            if embedding:
                embeddings.append(embedding)
        
        return embeddings
    
    # File Operations
    async def store_file(self, file_content: bytes, filename: str, content_type: str = None) -> str:
        """
        Store a file (photo, audio, document)
        
        Args:
            file_content: Raw file bytes
            filename: Original filename
            content_type: MIME type
            
        Returns:
            str: Unique file ID
        """
        file_id = str(uuid.uuid4())
        file_ext = Path(filename).suffix
        stored_filename = f"{file_id}{file_ext}"
        file_path = self.files_dir / stored_filename
        
        try:
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(file_content)
            
            # Store file metadata
            metadata = {
                'id': file_id,
                'original_filename': filename,
                'stored_filename': stored_filename,
                'content_type': content_type,
                'size': len(file_content),
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            
            key = f"files.metadata.{file_id}"
            await self.backend.write(key, metadata)
            
            logger.info(f"Stored file: {filename} as {file_id}")
            return file_id
            
        except IOError as e:
            raise StorageError(f"Failed to store file {filename}: {e}")
    
    async def get_file(self, file_id: str) -> Optional[tuple[bytes, Dict[str, Any]]]:
        """Retrieve file content and metadata"""
        # Get metadata first
        metadata_key = f"files.metadata.{file_id}"
        metadata = await self.backend.read(metadata_key)
        
        if not metadata:
            return None
        
        # Read file content
        file_path = self.files_dir / metadata['stored_filename']
        
        try:
            async with aiofiles.open(file_path, 'rb') as f:
                content = await f.read()
            return content, metadata
        except IOError:
            logger.error(f"File content missing for {file_id}")
            return None
    
    async def delete_file(self, file_id: str) -> bool:
        """Delete a file and its metadata"""
        # Get metadata to find stored filename
        metadata_key = f"files.metadata.{file_id}"
        metadata = await self.backend.read(metadata_key)
        
        if not metadata:
            return False
        
        # Delete file
        file_path = self.files_dir / metadata['stored_filename']
        try:
            if file_path.exists():
                file_path.unlink()
        except IOError:
            pass
        
        # Delete metadata
        await self.backend.delete(metadata_key)
        return True
    
    # Cache Operations
    async def cache_set(self, key: str, data: Any, ttl_seconds: int = 3600) -> bool:
        """Store data in cache with TTL"""
        cache_data = {
            'data': data,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'expires_at': (datetime.now(timezone.utc).timestamp() + ttl_seconds)
        }
        
        cache_key = f"cache.{key}"
        await self.backend.write(cache_key, cache_data)
        return True
    
    async def cache_get(self, key: str) -> Optional[Any]:
        """Retrieve data from cache, checking TTL"""
        cache_key = f"cache.{key}"
        cache_data = await self.backend.read(cache_key)
        
        if not cache_data:
            return None
        
        # Check if expired
        if datetime.now(timezone.utc).timestamp() > cache_data.get('expires_at', 0):
            await self.backend.delete(cache_key)  # Clean up expired cache
            return None
        
        return cache_data.get('data')
    
    async def cache_delete(self, key: str) -> bool:
        """Delete cache entry"""
        cache_key = f"cache.{key}"
        return await self.backend.delete(cache_key)
    
    # Utility Operations
    async def health_check(self) -> Dict[str, Any]:
        """Check storage service health"""
        try:
            # Test write/read/delete
            test_key = "health_check.test"
            test_data = {"timestamp": datetime.now(timezone.utc).isoformat()}
            
            await self.backend.write(test_key, test_data)
            read_data = await self.backend.read(test_key)
            await self.backend.delete(test_key)
            
            return {
                "status": "healthy",
                "backend": self.backend.__class__.__name__,
                "test_passed": read_data == test_data,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics"""
        try:
            memories_count = len(await self.backend.list_keys("memories.events"))
            embeddings_count = len(await self.backend.list_keys("embeddings"))
            files_count = len(await self.backend.list_keys("files.metadata"))
            cache_count = len(await self.backend.list_keys("cache"))
            
            # Calculate total file size
            total_file_size = 0
            if self.files_dir.exists():
                for file_path in self.files_dir.iterdir():
                    if file_path.is_file():
                        total_file_size += file_path.stat().st_size
            
            return {
                "memories_count": memories_count,
                "embeddings_count": embeddings_count,
                "files_count": files_count,
                "cache_count": cache_count,
                "total_file_size_bytes": total_file_size,
                "storage_backend": self.backend.__class__.__name__
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"error": str(e)}


# Singleton instance for easy import
storage_service = StorageService()


# Example usage and testing
# async def main():
#     """Example usage of the storage service"""
    
#     # Initialize storage service
#     service = StorageService()
    
#     # Health check
#     health = await service.health_check()
#     print(f"Storage health: {health}")
    
#     # Store a memory
#     memory_data = {
#         "title": "Met Jennifer at TechCrunch",
#         "description": "Great conversation about Stripe's crypto APIs",
#         "people": ["Jennifer Chen"],
#         "location": "TechCrunch Conference",
#         "tags": ["networking", "conference", "crypto"],
#         "emotional_context": "excited",
#         "type": "conversation"
#     }
    
#     memory_id = await service.store_memory(memory_data)
#     print(f"Stored memory: {memory_id}")
    
#     # Retrieve the memory
#     retrieved = await service.get_memory(memory_id)
#     print(f"Retrieved memory: {retrieved['title']}")
    
#     # Store an embedding
#     await service.store_embedding(
#         memory_id, 
#         [0.1, 0.2, 0.3] * 100,  # Mock embedding vector
#         {"type": "memory", "content": memory_data["description"]}
#     )
    
#     # Cache some data
#     await service.cache_set("api_response_123", {"result": "success"}, ttl_seconds=60)
#     cached_data = await service.cache_get("api_response_123")
#     print(f"Cached data: {cached_data}")
    
#     # Get storage stats
#     stats = await service.get_stats()
#     print(f"Storage stats: {stats}")


# if __name__ == "__main__":
#     asyncio.run(main())