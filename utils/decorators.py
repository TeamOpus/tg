import functools
import asyncio
import time
import logging
from typing import Callable, Optional, Union, Any
from pyrogram.types import Message, CallbackQuery
from config.config import settings
from database.models import User
from utils.helpers import is_admin, mention_user
from handlers.errors import ErrorHandler
from asyncio import Lock

logger = logging.getLogger(__name__)

class Decorators:
    # Locks for thread-safe state management
    _rate_limit_lock = Lock()
    _cooldown_lock = Lock()

    @staticmethod
    def capture_errors(func: Callable) -> Callable:
        """Capture and handle errors gracefully, logging unexpected issues.

        Args:
            func: The function to decorate.

        Returns:
            Callable: Wrapped function with error handling.

        Example:
            @Decorators.capture_errors
            async def my_command(client, message):
                # Command logic
        """
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
                if update:
                    await ErrorHandler._handle_unexpected_error(e, update, func.__name__)
                else:
                    logger.error(
                        f"Unhandled error in {func.__name__}: {str(e)}",
                        exc_info=True,
                        extra={'args': args, 'kwargs': kwargs}
                    )
        return wrapper

    @staticmethod
    def rate_limit(limit: int = 5, window: int = 60) -> Callable:
        """Rate limit function calls per user within a time window.

        Args:
            limit: Maximum number of calls allowed in the window.
            window: Time window in seconds.

        Returns:
            Callable: Decorator function.

        Raises:
            ValueError: If limit or window is negative or zero.

        Example:
            @Decorators.rate_limit(limit=3, window=30)
            async def my_command(client, message):
                # Command logic
        """
        if limit <= 0 or window <= 0:
            raise ValueError("Rate limit and window must be positive integers")
        
        rate_limits = {}

        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
                if not update:
                    return await func(*args, **kwargs)

                user_id = getattr(update.from_user, 'id', None)
                if not user_id:
                    logger.warning(f"No user_id found in update for {func.__name__}")
                    return await func(*args, **kwargs)

                current_time = time.time()
                async with Decorators._rate_limit_lock:
                    if user_id not in rate_limits:
                        rate_limits[user_id] = {'count': 0, 'time': current_time}

                    if current_time - rate_limits[user_id]['time'] > window:
                        rate_limits[user_id] = {'count': 1, 'time': current_time}
                    else:
                        rate_limits[user_id]['count'] += 1

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
        """Restrict access to admin users only.

        Args:
            func: The function to decorate.

        Returns:
            Callable: Wrapped function with admin check.

        Example:
            @Decorators.admin_only
            async def admin_command(client, message):
                # Admin-only logic
        """
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
            if not update:
                logger.warning(f"Admin check failed - no message/callback in args for {func.__name__}")
                return

            chat_id = getattr(update, 'chat', None)
            user_id = getattr(update.from_user, 'id', None)
            if not chat_id or not user_id:
                logger.warning(f"Missing chat_id or user_id in {func.__name__}")
                return

            if not is_admin(chat_id.id, user_id):
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
        """Ensure the bot is in a voice chat before executing.

        Args:
            func: The function to decorate.

        Returns:
            Callable: Wrapped function with voice chat check.

        Example:
            @Decorators.require_voice_chat
            async def voice_command(client, message):
                # Voice chat logic
        """
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            client = args[0] if args else None
            update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
            if not update or not client:
                logger.warning(f"Missing client or update in {func.__name__}")
                return await func(*args, **kwargs)

            chat_id = getattr(update, 'chat', None)
            if not chat_id:
                logger.warning(f"No chat_id found in update for {func.__name__}")
                return await func(*args, **kwargs)

            if not await client.is_voice_chat_active(chat_id.id):
                if isinstance(update, Message):
                    await update.reply("❗ I need to be in a voice chat first!")
                elif isinstance(update, CallbackQuery):
                    await update.answer("Join a voice chat first!", show_alert=True)
                return

            return await func(*args, **kwargs)
        return wrapper

    @staticmethod
    def validate_args(*validators: Callable) -> Callable:
        """Validate command arguments with custom validator functions.

        Args:
            validators: Variable number of validator functions.

        Returns:
            Callable: Decorator function.

        Example:
            def check_args(args): assert len(args) > 0, "Missing arguments"
            @Decorators.validate_args(check_args)
            async def my_command(client, message):
                # Command logic
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
                if not update:
                    return await func(*args, **kwargs)

                command_args = []
                if isinstance(update, Message) and hasattr(update, 'text') and update.text:
                    command_args = update.text.split()[1:]

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
        """Log function execution details.

        Args:
            log_args: Whether to log function arguments.

        Returns:
            Callable: Decorator function.

        Example:
            @Decorators.log_execution(log_args=True)
            async def my_command(client, message):
                # Command logic
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)

                logger.info(f"Executing {func.__name__} (Update: {update})")
                if log_args:
                    logger.debug(f"Args: {args}, Kwargs: {kwargs}")

                try:
                    result = await func(*args, **kwargs)
                    exec_time = time.time() - start_time
                    logger.info(f"Completed {func.__name__} in {exec_time:.2f}s")
                    return result
                except Exception as e:
                    exec_time = time.time() - start_time
                    logger.error(
                        f"Failed {func.__name__} after {exec_time:.2f}s: {str(e)}",
                        exc_info=True
                    )
                    raise
            return wrapper
        return decorator

    @staticmethod
    def ensure_database_user(func: Callable) -> Callable:
        """Ensure the user exists in the database before executing.

        Args:
            func: The function to decorate.

        Returns:
            Callable: Wrapped function with user database check.

        Example:
            @Decorators.ensure_database_user
            async def my_command(client, message, db_user=None):
                # Use db_user
        """
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
            if not update:
                return await func(*args, **kwargs)

            user_id = getattr(update.from_user, 'id', None)
            if not user_id:
                logger.warning(f"No user_id found in update for {func.__name__}")
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

    @staticmethod
    def cooldown(seconds: int = 5) -> Callable:
        """Add cooldown period to command execution.

        Args:
            seconds: Cooldown period in seconds.

        Returns:
            Callable: Decorator function.

        Raises:
            ValueError: If seconds is negative or zero.

        Example:
            @Decorators.cooldown(seconds=10)
            async def my_command(client, message):
                # Command logic
        """
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
                    logger.warning(f"No user_id found in update for {func.__name__}")
                    return await func(*args, **kwargs)

                current_time = time.time()
                async with Decorators._cooldown_lock:
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
        """Retry async function on failure with exponential backoff.

        Args:
            max_retries: Maximum number of retry attempts.
            delay: Initial delay between retries in seconds.

        Returns:
            Callable: Decorator function.

        Raises:
            ValueError: If max_retries or delay is negative or zero.

        Example:
            @Decorators.async_retry(max_retries=3, delay=2.0)
            async def my_command(client, message):
                # Command logic
        """
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
                        logger.warning(
                            f"Attempt {attempt + 1} failed for {func.__name__}. "
                            f"Retrying in {wait_time:.1f}s... Error: {str(e)}",
                            exc_info=True
                        )
                        await asyncio.sleep(wait_time)

                raise last_exception if last_exception else Exception("Unknown error")
            return wrapper
        return decorator

    @staticmethod
    def check_ban_status(func: Callable) -> Callable:
        """Check if user is banned before executing command.

        Args:
            func: The function to decorate.

        Returns:
            Callable: Wrapped function with ban status check.

        Example:
            @Decorators.check_ban_status
            async def my_command(client, message):
                # Command logic
        """
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            update = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
            if not update:
                return await func(*args, **kwargs)

            user_id = getattr(update.from_user, 'id', None)
            if not user_id:
                logger.warning(f"No user_id found in update for {func.__name__}")
                return await func(*args, **kwargs)

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
