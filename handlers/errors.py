import logging
from typing import Callable, Any, Union
from functools import wraps
from pyrogram import Client
from pyrogram.types import Message, CallbackQuery
from pyrogram.errors import (
    FloodWait,
    RPCError,
    BadRequest,
    Unauthorized,
    Forbidden,
    NotAcceptable,
    ChatAdminRequired,
    PeerIdInvalid,
    ChannelPrivate,
    UserNotParticipant,
    MessageNotModified,
    MessageDeleteForbidden
)
from config.config import settings
from utils.helpers import error_emoji
import traceback
import time

logger = logging.getLogger(__name__)

class ErrorHandler:
    _rate_limit_cache = {}
    _last_notify_time = 0

    @classmethod
    def capture_errors(cls, func: Callable) -> Callable:
        """Decorator to capture and handle errors gracefully."""
        @wraps(func)
        async def wrapper(client: Client, update: Union[Message, CallbackQuery], *args, **kwargs):
            try:
                return await func(client, update, *args, **kwargs)
            except FloodWait as e:
                await cls._handle_flood_wait(e, update)
            except MessageNotModified:
                pass  # Silent pass for message not modified errors
            except (BadRequest, PeerIdInvalid, ChannelPrivate) as e:
                await cls._handle_bad_request(e, update)
            except (Unauthorized, Forbidden, UserNotParticipant) as e:
                await cls._handle_permission_error(e, update)
            except NotAcceptable:
                await cls._handle_not_acceptable(update)
            except TimedOut:
                await cls._handle_timeout(update)
            except ChatAdminRequired:
                await cls._handle_admin_required(update)
            except MessageDeleteForbidden:
                await cls._handle_message_delete_forbidden(update)
            except RPCError as e:
                await cls._handle_rpc_error(e, update)
            except Exception as e:
                await cls._handle_unexpected_error(e, update, func.__name__)
        return wrapper

    @classmethod
    async def _handle_flood_wait(cls, e: FloodWait, update: Union[Message, CallbackQuery]):
        wait_time = e.value
        err_msg = f"{error_emoji()} Too many requests. Please wait {wait_time} seconds."
        
        logger.warning(f"FloodWait: Need to wait {wait_time}s")
        await cls._notify_user(update, err_msg)
        time.sleep(wait_time)

    @classmethod
    async def _handle_bad_request(cls, e: BadRequest, update: Union[Message, CallbackQuery]):
        err_msg = f"{error_emoji()} Invalid request: {str(e)}"
        logger.error(f"BadRequest: {str(e)}")
        await cls._notify_user(update, err_msg)

    @classmethod
    async def _handle_permission_error(cls, e: Union[Unauthorized, Forbidden], update: Union[Message, CallbackQuery]):
        err_msg = f"{error_emoji()} I don't have permission to do that."
        logger.error(f"PermissionError: {str(e)}")
        await cls._notify_user(update, err_msg)

    @classmethod
    async def _handle_not_acceptable(cls, update: Union[Message, CallbackQuery]):
        err_msg = f"{error_emoji()} This action isn't allowed right now."
        logger.warning("NotAcceptable error")
        await cls._notify_user(update, err_msg)

    @classmethod
    async def _handle_timeout(cls, update: Union[Message, CallbackQuery]):
        err_msg = f"{error_emoji()} Request timed out. Please try again."
        logger.warning("Request timeout")
        await cls._notify_user(update, err_msg)

    @classmethod
    async def _handle_admin_required(cls, update: Union[Message, CallbackQuery]):
        err_msg = f"{error_emoji()} I need admin permissions to do that."
        logger.warning("Admin required")
        await cls._notify_user(update, err_msg)

    @classmethod
    async def _handle_message_delete_forbidden(cls, update: Union[Message, CallbackQuery]):
        logger.warning("Message delete forbidden")
        # No notification needed for this case

    @classmethod
    async def _handle_rpc_error(cls, e: RPCError, update: Union[Message, CallbackQuery]):
        err_msg = f"{error_emoji()} A Telegram error occurred. Please try again."
        logger.error(f"RPCError: {str(e)}")
        await cls._notify_user(update, err_msg)

    @classmethod
    async def _handle_unexpected_error(cls, e: Exception, update: Union[Message, CallbackQuery], func_name: str):
        err_msg = f"{error_emoji()} An unexpected error occurred. The admin has been notified."
        logger.critical(
            f"Unexpected error in {func_name}: {str(e)}\n"
            f"Traceback: {traceback.format_exc()}"
        )
        await cls._notify_user(update, err_msg)
        await cls._notify_admin(e, func_name)

    @classmethod
    async def _notify_user(cls, update: Union[Message, CallbackQuery], message: str):
        """Send error notification to user with rate limiting."""
        current_time = time.time()
        user_id = update.from_user.id if hasattr(update, 'from_user') else update.message.chat.id
        
        # Rate limit notifications (1 per 10 seconds per user)
        if user_id in cls._rate_limit_cache:
            if current_time - cls._rate_limit_cache[user_id] < 10:
                return
        cls._rate_limit_cache[user_id] = current_time
        
        try:
            if isinstance(update, CallbackQuery):
                await update.answer(message, show_alert=True)
            else:
                await update.reply(message)
        except Exception as e:
            logger.error(f"Failed to send error notification: {e}")

    @classmethod
    async def _notify_admin(cls, error: Exception, func_name: str):
        """Notify bot admin about critical errors."""
        if not settings.ADMINS:
            return
            
        current_time = time.time()
        # Rate limit admin notifications (1 per minute)
        if current_time - cls._last_notify_time < 60:
            return
            
        cls._last_notify_time = current_time
        
        from handlers.commands import CommandHandler  # Avoid circular import
        try:
            error_msg = (
                f"🚨 **Critical Error** 🚨\n\n"
                f"**Function:** `{func_name}`\n"
                f"**Error:** `{str(error)}`\n"
                f"```{traceback.format_exc()}```"
            )
            
            for admin_id in settings.ADMINS:
                try:
                    await CommandHandler.app.send_message(
                        admin_id,
                        error_msg,
                        parse_mode="markdown"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_id}: {e}")
        except Exception as e:
            logger.error(f"Failed to prepare admin notification: {e}")

def error_emoji() -> str:
    """Get a random error emoji"""
    import random
    emojis = ["❌", "⚠️", "🚫", "⛔", "🔴", "💢"]
    return random.choice(emojis)

