import logging
import sys
from typing import Optional

def setup_logging(level: str = "INFO", format_string: Optional[str] = None) -> logging.Logger:
    """Setup structured logging configuration."""
    
    if format_string is None:
        format_string = (
            "%(asctime)s - %(name)s - %(levelname)s - "
            "[%(filename)s:%(lineno)d] - %(message)s"
        )
    
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=format_string,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("logs/app.log", mode="a")
        ]
    )
    
    return logging.getLogger(__name__)

def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a specific module."""
    return logging.getLogger(name)