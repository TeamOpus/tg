import functools
import asyncio
import time
import logging
from typing import Callable, Optional, Union, Any
from pyrogram.types import Message, CallbackQuery
from config.config import settings
from database.models import User
from utils.helpers import is_admin, mention_user
from utils.errors import ErrorHandler
import inspect

logger = logging.getLogger(__name__)

class Decorators:
    @staticmethod
    def capture_errors(func: Callable) -> Callable:
        """Decorator to capture and handle errors gracefully"""
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                # Get the appropriate update object from args
                update = None
                for arg in args:
                    if isinstance(arg, (Message, CallbackQuery)):
                        update = arg
                        break
                
                if update:
                    await ErrorHandler._handle_unexpected_error(e, update, func.__name__)
                else:
                    logger.error(f"Unhandled error in {func.__name__}: {str(e)}", exc_info=True)
        return wrapper

    @staticmethod
    def rate_limit(limit: int = 5, window: int = 60) -> Callable:
        """Decorator to rate limit function calls"""
        def decorator(func: Callable) -> Callable:
            rate_limits = {}

            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                # Get the appropriate update object from args
                update = None
                for arg in args:
                    if isinstance(arg, (Message, CallbackQuery)):
                        update = arg
                        break
                
                if not update:
                    return await func(*args, **kwargs)

                user_id = update.from_user.id
                current_time = time.time()

                # Initialize user tracking
                if user_id not in rate_limits:
                    rate_limits[user_id] = {'count': 0, 'time': current_time}

                # Reset if window has passed
                if current_time - rate_limits[user_id]['time'] > window:
                    rate_limits[user_id] = {'count': 1, 'time': current_time}
                else:
                    rate_limits[user_id]['count'] += 1

                # Check limit
                if rate_limits[user_id]['count'] > limit:
                    if isinstance(update, Message):
                        await update.reply(
                            f"🚫 Too many requests! Please wait {window} seconds between commands."
                        )
                    elif isinstance(update, CallbackQuery):
                        await update.answer(
                            "Slow down! You're clicking too fast.",
                            show_alert=False
                        )
                    return
                
                return await func(*args, **kwargs)
            return wrapper
        return decorator

    @staticmethod
    def admin_only(func: Callable) -> Callable:
        """Restrict access to admin users only"""
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Get the appropriate update object from args
            update = None
            for arg in args:
                if isinstance(arg, (Message, CallbackQuery)):
                    update = arg
                    break
            
            if not update:
                logger.warning("Admin check failed - no message/callback in args")
                return

            if not is_admin(update.chat.id, update.from_user.id):
                if isinstance(update, Message):
                    await update.reply("⛔ This command is only available to admins.")
                elif isinstance(update, CallbackQuery):
                    await update.answer(
                        "You don't have permission to do that.",
                        show_alert=True
                    )
                return
            
            return await func(*args, **kwargs)
        return wrapper

    @staticmethod
    def require_voice_chat(func: Callable) -> Callable:
        """Ensure the bot is in a voice chat before executing"""
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # This assumes the first arg is the client and second is the update
            client = args[0]
            update = args[1]
            
            if not isinstance(update, (Message, CallbackQuery)):
                return await func(*args, **kwargs)

            chat_id = update.chat.id
            
            # Check if bot is in voice chat (implementation depends on your voice chat system)
            if not await client.is_voice_chat_active(chat_id):
                if isinstance(update, Message):
                    await update.reply("❗ I need to be in a voice chat first!")
                elif isinstance(update, CallbackQuery):
                    await update.answer("Join a voice chat first!", show_alert=True)
                return
            
            return await func(*args, **kwargs)
        return wrapper

    @staticmethod
    def validate_args(*validators: Callable) -> Callable:
        """Validate command arguments with custom validator functions"""
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                update = None
                for arg in args:
                    if isinstance(arg, (Message, CallbackQuery)):
                        update = arg
                        break
                
                if not update:
                    return await func(*args, **kwargs)

                # Extract command args
                if isinstance(update, Message):
                    command_args = update.text.split()[1:] if update.text else []
                else:
                    command_args = []
                
                # Run validators
                for validator in validators:
                    try:
                        validator(command_args)
                    except ValueError as e:
                        if isinstance(update, Message):
                            await update.reply(f"❌ Invalid arguments: {str(e)}")
                        elif isinstance(update, CallbackQuery):
                            await update.answer(str(e), show_alert=True)
                        return
                
                return await func(*args, **kwargs)
            return wrapper
        return decorator

    @staticmethod
    def log_execution(log_args: bool = False) -> Callable:
        """Log function execution details"""
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                
                # Get the calling update if available
                update = None
                for arg in args:
                    if isinstance(arg, (Message, CallbackQuery)):
                        update = arg
                        break
                
                # Log start
                logger.info(f"Executing {func.__name__} (Update: {update})")
                if log_args:
                    logger.debug(f"Args: {args}")
                    logger.debug(f"Kwargs: {kwargs}")
                
                try:
                    result = await func(*args, **kwargs)
                    exec_time = time.time() - start_time
                    logger.info(f"Completed {func.__name__} in {exec_time:.2f}s")
                    return result
                except Exception as e:
                    exec_time = time.time() - start_time
                    logger.error(f"Failed {func.__name__} after {exec_time:.2f}s: {str(e)}")
                    raise
            return wrapper
        return decorator

    @staticmethod
    def ensure_database_user(func: Callable) -> Callable:
        """Ensure the user exists in database before executing"""
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Get the update object
            update = None
            for arg in args:
                if isinstance(arg, (Message, CallbackQuery)):
                    update = arg
                    break
            
            if not update:
                return await func(*args, **kwargs)

            # Get or create user in database
            user_id = update.from_user.id
            user = await User.get_or_create(
                user_id=user_id,
                defaults={
                    'username': update.from_user.username,
                    'first_name': update.from_user.first_name,
                    'last_name': update.from_user.last_name
                }
            )
            
            # Add user to kwargs
            kwargs['db_user'] = user
            return await func(*args, **kwargs)
        return wrapper

    @staticmethod
    def cooldown(seconds: int = 5) -> Callable:
        """Add cooldown period to command execution"""
        def decorator(func: Callable) -> Callable:
            last_called = {}
            
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                # Get the update object
                update = None
                for arg in args:
                    if isinstance(arg, (Message, CallbackQuery)):
                        update = arg
                        break
                
                if not update:
                    return await func(*args, **kwargs)

                user_id = update.from_user.id
                current_time = time.time()
                
                if user_id in last_called:
                    elapsed = current_time - last_called[user_id]
                    if elapsed < seconds:
                        remaining = seconds - elapsed
                        if isinstance(update, Message):
                            await update.reply(
                                f"⏳ Please wait {remaining:.1f} seconds before using this command again."
                            )
                        elif isinstance(update, CallbackQuery):
                            await update.answer(
                                f"Wait {remaining:.1f}s before clicking again",
                                show_alert=False
                            )
                        return
                
                last_called[user_id] = current_time
                return await func(*args, **kwargs)
            return wrapper
        return decorator

    @staticmethod
    def async_retry(max_retries: int = 3, delay: float = 1.0) -> Callable:
        """Retry async function on failure with exponential backoff"""
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
                        logger.warning(
                            f"Attempt {attempt + 1} failed for {func.__name__}. "
                            f"Retrying in {wait_time:.1f}s... Error: {str(e)}"
                        )
                        await asyncio.sleep(wait_time)
                
                raise last_exception if last_exception else Exception("Unknown error")
            return wrapper
        return decorator

    @staticmethod
    def check_ban_status(func: Callable) -> Callable:
        """Check if user is banned before executing command"""
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Get the update object
            update = None
            for arg in args:
                if isinstance(arg, (Message, CallbackQuery)):
                    update = arg
                    break
            
            if not update:
                return await func(*args, **kwargs)

            # Check ban status (implementation depends on your database)
            user_id = update.from_user.id
            is_banned = await User.is_banned(user_id)
            
            if is_banned:
                if isinstance(update, Message):
                    await update.reply("🚫 You are banned from using this bot.")
                elif isinstance(update, CallbackQuery):
                    await update.answer("You are banned", show_alert=True)
                return
            
            return await func(*args, **kwargs)
        return wrapper

decorators = Decorators()

