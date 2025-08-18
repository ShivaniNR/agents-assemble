from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import voice_routes#, memory_routes
from utils.config import settings
from utils.logging_config import setup_logging

def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    
    # Setup logging
    setup_logging(level=settings.LOG_LEVEL)
    
    # Create FastAPI app
    app = FastAPI(
        title=settings.API_TITLE,
        version=settings.API_VERSION
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_CREDENTIALS,
        allow_methods=settings.CORS_METHODS,
        allow_headers=settings.CORS_HEADERS,
    )
    
    # Include routers
    app.include_router(voice_routes.router)
    #app.include_router(memory_routes.router)
    
    # Health check endpoint
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": settings.API_VERSION}
    
    return app