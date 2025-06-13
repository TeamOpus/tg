import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any
from config.config import settings
import json
import traceback
from datetime import datetime
import colorlog

class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_record: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        if record.exc_info:
            log_record["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]),
                "stacktrace": traceback.format_exc(),
            }
        
        return json.dumps(log_record)

def setup_logging():
    """Configure logging for the application"""
    
    # Create logs directory if it doesn't exist
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # Base configuration
    log_level = getattr(logging, settings.LOG_LEVEL)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Clear existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Console Handler (colored output)
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        }
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File Handler (JSON format)
    if settings.LOG_FILE:
        file_handler = RotatingFileHandler(
            filename=logs_dir / settings.LOG_FILE,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(file_handler)
    
    # Sentry Handler (if configured)
    if settings.SENTRY_DSN:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.logging import LoggingIntegration
            
            sentry_logging = LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR
            )
            
            sentry_sdk.init(
                dsn=settings.SENTRY_DSN.get_secret_value(),
                integrations=[sentry_logging],
                traces_sample_rate=1.0,
                environment="production"
            )
        except ImportError:
            root_logger.warning("Sentry SDK not installed. Error tracking disabled.")
        except Exception as e:
            root_logger.error(f"Failed to initialize Sentry: {e}")
    
    # Configure third-party loggers
    for logger_name in ['pyrogram', 'pytgcalls', 'urllib3', 'asyncio']:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    
    # Silence noisy loggers
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    logging.getLogger('spotipy').setLevel(logging.INFO)
    
    # Initial log message
    logger = logging.getLogger(__name__)
    logger.info("Logging configured successfully")
    logger.debug("Debug logging enabled")
    
    # Add exception hook for uncaught exceptions
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        logger.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback)
        )
    
    sys.excepthook = handle_exception

class LoguruCompatHandler(logging.Handler):
    """Compatibility handler for code expecting loguru-style logging"""
    
    def emit(self, record):
        try:
            msg = self.format(record)
            if record.levelno >= logging.ERROR:
                print(msg, file=sys.stderr)
            else:
                print(msg)
        except Exception:
            self.handleError(record)

def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a configured logger instance with optional name"""
    logger = logging.getLogger(name or __name__)
    return logger

# Initialize logging when module is imported
setup_logging()
