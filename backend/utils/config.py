import os
from typing import List
from pydantic import BaseSettings

class Settings(BaseSettings):
    # API Configuration
    API_TITLE: str = "Voice AI API"
    API_VERSION: str = "1.0.0"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = True
    LOG_LEVEL: str = "info"
    
    # CORS Configuration
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:3001"]
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: List[str] = ["*"]
    CORS_HEADERS: List[str] = ["*"]
    
    # Session Configuration
    SESSION_TIMEOUT_MINUTES: int = 30
    
    # Storage Configuration
    DATA_DIR: str = "data"
    MEMORIES_DIR: str = "data/memories"
    CACHE_DIR: str = "data/cache"
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()

# import os
# import subprocess
# import sys

# def setup_ai_services():
#     """Setup script for AI services"""
    
#     print("🚀 Setting up AI services for Memory Agent...")
    
#     # Check environment variables
#     required_env_vars = {
#         "GEMINI_API_KEY": "Get from https://makersuite.google.com/app/apikey",
#         "GOOGLE_APPLICATION_CREDENTIALS": "Path to Google Cloud service account JSON"
#     }
    
#     missing_vars = []
#     for var, description in required_env_vars.items():
#         if not os.getenv(var):
#             missing_vars.append(f"❌ {var}: {description}")
#         else:
#             print(f"✅ {var}: Set")
    
#     if missing_vars:
#         print("\n⚠️ Missing environment variables:")
#         for var in missing_vars:
#             print(f"   {var}")
#         print("\nPlease set these environment variables before running the Memory Agent.")
    
#     # Download SpaCy model
#     try:
#         print("\n📥 Downloading SpaCy model...")
#         subprocess.run([sys.executable, "-m", "spacy", "download", "en_core_web_sm"], check=True)
#         print("✅ SpaCy model downloaded successfully")
#     except subprocess.CalledProcessError:
#         print("❌ Failed to download SpaCy model. Please run manually:")
#         print("   python -m spacy download en_core_web_sm")
    
#     # Test imports
#     print("\n🧪 Testing AI service imports...")
    
#     test_imports = {
#         "google.generativeai": "Gemini API",
#         "sentence_transformers": "Sentence Transformers",
#         "google.cloud.language": "Google Cloud Language",
#         "spacy": "SpaCy NLP"
#     }
    
#     for module, name in test_imports.items():
#         try:
#             __import__(module)
#             print(f"✅ {name}: Available")
#         except ImportError:
#             print(f"❌ {name}: Not available - install with: pip install {module.replace('.', '-')}")
    
#     print("\n🎉 Setup complete! Your Memory Agent should be ready to use.")

# if __name__ == "__main__":
#     setup_ai_services()