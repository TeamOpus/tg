import functools
import asyncio
import time
import logging
from typing import Callable
from pyrogram.types import Message, CallbackQuery
from config.config import settings
from database.models import User
from utils.helpers import is_admin
from handlers.errors import ErrorHandler
from asyncio import Lock

logger = logging.getLogger(__name__)

# Locks for thread-safe state management
_rate_limit_lock = Lock()
_cooldown_lock = Lock()

def capture_errors(func: Callable) -> Callable:
    """Decorator to capture and handle errors gracefully."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
            if update:
                await ErrorHandler._handle_unexpected_error(e, update, func.__name__)
            else:
                logger.error(f"Unhandled error in {func.__name__}: {str(e)}", exc_info=True)
    return wrapper

def rate_limit(limit: int = 5, window: int = 60) -> Callable:
    """Decorator to rate limit function calls."""
    if limit <= 0 or window <= 0:
        raise ValueError("Rate limit and window must be positive")
    
    rate_limits = {}

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
            if not update:
                return await func(*args, **kwargs)
            
            user_id = getattr(update.from_user, 'id', None)
            if not user_id:
                logger.warning(f"No user_id in {func.__name__}")
                return await func(*args, **kwargs)
            
            current_time = time.time()
            async with _rate_limit_lock:
                if user_id not in rate_limits or current_time - rate_limits[user_id]['time'] > window:
                    rate_limits[user_id] = {'count': 1, 'time': current_time}
                else:
                    rate_limits[user_id]['count'] += 1
                    if rate_limits[user_id]['count'] > limit:
                        if isinstance(update, Message):
                            await update.reply(f"🚫 Too many requests! Please wait {window} seconds.")
                        else:
                            await update.answer("Slow down!", show_alert=False)
                        return
            return await func(*args, **kwargs)
        return wrapper
    return decorator

def admin_only(func: Callable) -> Callable:
    """Restrict access to admin users only."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
        if not update:
            logger.warning(f"No update in {func.__name__}")
            return
        if not is_admin(getattr(update.chat, 'id', None), getattr(update.from_user, 'id', None)):
            if isinstance(update, Message):
                await update.reply("⛔ Admins only.")
            elif isinstance(update, CallbackQuery):
                await update.answer("You don't have permission.", show_alert=True)
            return
        return await func(*args, **kwargs)
    return wrapper

def require_voice_chat(func: Callable) -> Callable:
    """Ensure the bot is in a voice chat before executing."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        client = args[0] if args else None
        update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
        if not update or not client:
            logger.warning(f"Missing client or update in {func.__name__}")
            return await func(*args, **kwargs)
        
        chat_id = getattr(update.chat, 'id', None)
        if not chat_id:
            logger.warning(f"No chat_id in {func.__name__}")
            return await func(*args, **kwargs)
        
        if not await client.is_voice_chat_active(chat_id):
            if isinstance(update, Message):
                await update.reply("❗ Join a voice chat first.")
            elif isinstance(update, CallbackQuery):
                await update.answer("Join a voice chat first!", show_alert=True)
            return
        return await func(*args, **kwargs)
    return wrapper

def validate_args(*validators: Callable) -> Callable:
    """Validate command arguments with custom validator functions."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
            if not update:
                return await func(*args, **kwargs)
            
            command_args = update.text.split()[1:] if isinstance(update, Message) and getattr(update, 'text', None) else []
            for validator in validators:
                try:
                    validator(command_args)
                except ValueError as e:
                    if isinstance(update, Message):
                        await update.reply(f"❌ Invalid arguments: {str(e)}")
                    else:
                        await update.answer(str(e), show_alert=True)
                    return
            return await func(*args, **kwargs)
        return wrapper
    return decorator

def log_execution(log_args: bool = False) -> Callable:
    """Log function execution details."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
            logger.info(f"Executing {func.__name__} (Update: {update})")
            if log_args:
                logger.debug(f"Args: {args}")
                logger.debug(f"Kwargs: {kwargs}")
            try:
                result = await func(*args, **kwargs)
                logger.info(f"Completed {func.__name__} in {time.time() - start_time:.2f}s")
                return result
            except Exception as e:
                logger.error(f"Failed {func.__name__} after {time.time() - start_time:.2f}s: {str(e)}")
                raise
        return wrapper
    return decorator

def ensure_database_user(func: Callable) -> Callable:
    """Ensure the user exists in database before executing."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
        if not update:
            return await func(*args, **kwargs)
        
        user_id = getattr(update.from_user, 'id', None)
        if not user_id:
            logger.warning(f"No user_id in {func.__name__}")
            return await func(*args, **kwargs)
        
        user = await User.get_or_create(
            user_id=user_id,
            defaults={
                'username': getattr(update.from_user, 'username', None),
                'first_name': getattr(update.from_user, 'first_name', None),
                'last_name': getattr(update.from_user, 'last_name', None)
            }
        )
        kwargs['db_user'] = user
        return await func(*args, **kwargs)
    return wrapper

def cooldown(seconds: int = 5) -> Callable:
    """Add cooldown period to command execution."""
    if seconds <= 0:
        raise ValueError("Cooldown seconds must be positive")
    
    last_called = {}

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
            if not update:
                return await func(*args, **kwargs)
            
            user_id = getattr(update.from_user, 'id', None)
            if not user_id:
                logger.warning(f"No user_id in {func.__name__}")
                return await func(*args, **kwargs)
            
            current_time = time.time()
            async with _cooldown_lock:
                if user_id in last_called:
                    elapsed = current_time - last_called[user_id]
                    if elapsed < seconds:
                        remaining = seconds - elapsed
                        if isinstance(update, Message):
                            await update.reply(f"⏳ Wait {remaining:.1f}s.")
                        else:
                            await update.answer(f"Wait {remaining:.1f}s.", show_alert=False)
                        return
                last_called[user_id] = current_time
            return await func(*args, **kwargs)
        return wrapper
    return decorator

def async_retry(max_retries: int = 3, delay: float = 1.0) -> Callable:
    """Retry async function on failure with exponential backoff."""
    if max_retries <= 0 or delay <= 0:
        raise ValueError("Max retries and delay must be positive")
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    wait_time = delay * (2 ** attempt)
                    logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {wait_time:.1f}s")
                    await asyncio.sleep(wait_time)
            raise last_exception or Exception("Unknown async retry failure")
        return wrapper
    return decorator

def check_ban_status(func: Callable) -> Callable:
    """Check if user is banned before executing command."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
        if not update:
            return await func(*args, **kwargs)
        
        user_id = getattr(update.from_user, 'id', None)
        if not user_id:
            logger.warning(f"No user_id in {func.__name__}")
            return await func(*args, **kwargs)
        
        if await User.is_banned(user_id):
            if isinstance(update, Message):
                await update.reply("🚫 You are banned.")
            else:
                await update.answer("You are banned", show_alert=True)
            return
        return await func(*args, **kwargs)
    return wrapper
