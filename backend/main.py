import uvicorn
from api.app import create_app
from utils.config import settings

# Create the FastAPI application
app = create_app()

if __name__ == "__main__":
    print(f"Starting {settings.API_TITLE} v{settings.API_VERSION}")
    print(f"Server will run at: http://{settings.HOST}:{settings.PORT}")
    print(f"API Documentation: http://{settings.HOST}:{settings.PORT}/docs")
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
        log_level=settings.LOG_LEVEL.lower()
    )