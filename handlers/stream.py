from pytgcalls import PyTgCalls
from pytgcalls.types import Update, ChatUpdate
from pytgcalls.types.stream import (
    StreamAudioEnded,
    StreamVideoEnded,
    StreamDeleted
)
from services.player import Player
from services.queue import QueueService
from utils.helpers import format_duration
from utils.decorators import capture_errors
from database.models import QueueItem
import logging
import asyncio

logger = logging.getLogger(__name__)

class StreamHandler:
    def __init__(self, pytgcalls: PyTgCalls, player: Player):
        self.pytgcalls = pytgcalls
        self.player = player
        self.active_chats = set()
        self.register_handlers()

    def register_handlers(self):
        @self.pytgcalls.on_update()
        @capture_errors
        async def on_update(_, update: Update):
            if isinstance(update, ChatUpdate):
                await self._handle_chat_update(update)
            elif isinstance(update, (StreamAudioEnded, StreamVideoEnded, StreamDeleted)):
                await self._handle_stream_end(update)

        @self.pytgcalls.on_kicked()
        @capture_errors
        async def on_kicked(chat_id: int):
            await self._cleanup_chat(chat_id)
            logger.info(f"Bot was kicked from chat {chat_id}")

        @self.pytgcalls.on_left()
        @capture_errors
        async def on_left(chat_id: int):
            await self._cleanup_chat(chat_id)
            logger.info(f"Bot left chat {chat_id}")

        @self.pytgcalls.on_participants_change()
        @capture_errors
        async def on_participants_change(update: ChatUpdate):
            if update.status == ChatUpdate.Status.LEFT_VOICE_CHAT:
                await self._check_empty_chat(update.chat_id)

    async def _handle_chat_update(self, update: ChatUpdate):
        """Handle voice chat status updates"""
        chat_id = update.chat_id
        
        if update.status == ChatUpdate.Status.JOINED_VOICE_CHAT:
            logger.info(f"Joined voice chat in {chat_id}")
            self.active_chats.add(chat_id)
            
        elif update.status == ChatUpdate.Status.LEFT_VOICE_CHAT:
            logger.info(f"Left voice chat in {chat_id}")
            await self._cleanup_chat(chat_id)
            
        elif update.status == ChatUpdate.Status.INCOMING_CALL:
            logger.info(f"Incoming call in {chat_id}")
            # You could auto-answer here if desired
            # await self.pytgcalls.join_call(chat_id)

    async def _handle_stream_end(self, update: Update):
        """Handle stream playback completion"""
        chat_id = update.chat_id
        logger.info(f"Stream ended in chat {chat_id}")
        
        # Get current item before cleanup
        current_item = await QueueService.get_current_item(chat_id)
        
        # Clean up the finished stream
        await self._cleanup_finished_stream(chat_id, current_item)
        
        # Play next item in queue
        await self.player.play_next(chat_id)
        
        # Notify if queue is empty
        if current_item and not await QueueService.get_next_item(chat_id):
            await self._notify_queue_empty(chat_id)

    async def _cleanup_finished_stream(self, chat_id: int, item: Optional[QueueItem]):
        """Clean up resources after stream ends"""
        if item and item.file_path and not item.is_live:
            try:
                # Schedule file deletion
                asyncio.create_task(self._delete_file_with_delay(item.file_path))
            except Exception as e:
                logger.error(f"Error scheduling file cleanup: {e}")

    async def _cleanup_chat(self, chat_id: int):
        """Clean up when leaving a voice chat"""
        if chat_id in self.active_chats:
            self.active_chats.remove(chat_id)
            await QueueService.clear_queue(chat_id)
            logger.info(f"Cleaned up resources for chat {chat_id}")

    async def _check_empty_chat(self, chat_id: int):
        """Check if voice chat is empty and leave if needed"""
        try:
            participants = await self.pytgcalls.get_participants(chat_id)
            if not participants:
                logger.info(f"Voice chat {chat_id} is empty, leaving...")
                await self.pytgcalls.leave_call(chat_id)
                await self._cleanup_chat(chat_id)
        except Exception as e:
            logger.error(f"Error checking voice chat participants: {e}")

    async def _notify_queue_empty(self, chat_id: int):
        """Notify chat when queue is empty"""
        from handlers.commands import CommandHandler  # Avoid circular import
        try:
            await CommandHandler.app.send_message(
                chat_id,
                "🎶 Queue is empty. Add more songs with /play!"
            )
        except Exception as e:
            logger.error(f"Error sending queue empty notification: {e}")

    @staticmethod
    async def _delete_file_with_delay(file_path: str, delay: int = 300):
        """Delete file after a delay"""
        await asyncio.sleep(delay)
        try:
            import os
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Deleted file: {file_path}")
        except Exception as e:
            logger.error(f"Error deleting file {file_path}: {e}")

    async def is_active_chat(self, chat_id: int) -> bool:
        """Check if bot is active in a voice chat"""
        return chat_id in self.active_chats
    
    