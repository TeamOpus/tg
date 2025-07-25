#!/usr/bin/env python3
import asyncio
import logging
import signal
import sys
from pyrogram import Client
from pyrogram.enums import ParseMode
from pytgcalls import PyTgCalls
from config.logging import setup_logging
from handlers import (
    CommandHandler,
    CallbackHandler,
    StreamHandler,
    ErrorHandler
)
from services import (
    YouTubeService,
    SpotifyService,
    QueueService,
    Player
)
from utils.ip_rotator import IPRotator
from database.mongodb import mongodb
from version import __version__

# Global flag for graceful shutdown
SHUTDOWN = False

async def shutdown(signal, loop):
    """Handle graceful shutdown"""
    global SHUTDOWN
    SHUTDOWN = True
    
    logger = logging.getLogger(__name__)
    logger.info(f"Received exit signal {signal.name}...")
    
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]
    
    logger.info("Canceling outstanding tasks")
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

async def startup():
    """Initialize all components"""
    logger = logging.getLogger(__name__)
    logger.info(f"Starting music bot v{__version__}")
    
    # Initialize services
    if settings.IP_ROTATION_ENABLED:
        await IPRotator.load_proxies()
        logger.info(f"Loaded {len(IPRotator._proxies)} proxies")
    
    # Initialize database connection
    try:
        await mongodb.client.admin.command('ping')
        logger.info("Connected to MongoDB")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise
    
    # Create Pyrogram client
    app = Client(
        name='music_bot',
        api_id=settings.API_ID,
        api_hash=settings.API_HASH,
        session_string=settings.SESSION_NAME,
        in_memory=True,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Initialize PyTgCalls
    pytgcalls = PyTgCalls(app)
    
    # Initialize services
    youtube_service = YouTubeService()
    spotify_service = SpotifyService()
    queue_service = QueueService()
    player = Player(pytgcalls)
    
    # Initialize handlers
    command_handler = CommandHandler(app, pytgcalls, player)
    callback_handler = CallbackHandler(app, pytgcalls, player)
    stream_handler = StreamHandler(pytgcalls, player)
    error_handler = ErrorHandler()
    
    logger.info("All components initialized")
    return app, pytgcalls

async def main():
    """Main application entry point"""
    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Setup signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(shutdown(s, loop))
        )
    
    try:
        # Initialize application
        app, pytgcalls = await startup()
        
        # Start clients
        await app.start()
        await pytgcalls.start()
        
        logger.info("Bot started successfully. Press Ctrl+C to stop.")
        
        # Keep the application running
        while not SHUTDOWN:
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.critical(f"Fatal error during startup: {e}", exc_info=True)
        sys.exit(1)
        
    finally:
        # Cleanup resources
        logger.info("Shutting down...")
        if 'pytgcalls' in locals():
            await pytgcalls.leave_call()
            await pytgcalls.stop()
        if 'app' in locals():
            await app.stop()
        logger.info("Shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.getLogger(__name__).critical(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
