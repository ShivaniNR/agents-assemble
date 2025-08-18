from functools import lru_cache
from core.inputProcessor import InputProcessor
from core.sessionManager import SessionManager
from services.storage_service import StorageService
from agents.memory_agent import MemoryAgent
from utils.config import settings

@lru_cache()
def get_session_manager() -> SessionManager:
    """Get session manager instance."""
    return SessionManager(session_timeout_minutes=settings.SESSION_TIMEOUT_MINUTES)

@lru_cache()
def get_storage_service() -> StorageService:
    """Get storage service instance."""
    return StorageService()

@lru_cache()
def get_input_processor() -> InputProcessor:
    """Get input processor instance."""
    return InputProcessor()