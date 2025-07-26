
from pytgcalls import GroupCall
from pytgcalls.types import GroupCallAction, GroupCallFileAction
from services.player import Player
from services.queue import QueueService
from utils.decorators import capture_errors
from database.models import QueueItem
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

class StreamHandler:
    def __init__(self, pytgcalls: PyTgCalls, player: Player):
        self.pytgcalls = pytgcalls
        self.player = player
        self.active_chats = set()
        self.register_handlers()

    def register_handlers(self):
        # Playback ended event
        @self.pytgcalls.on(GroupCallFileAction.PLAYOUT_ENDED)
        @capture_errors
        async def on_playout_ended(gc, _):
            chat_id = gc.chat_id
            logger.info(f"Playback ended in chat {chat_id}")
            current_item = await QueueService.get_current_item(chat_id)
            await self._cleanup_finished_stream(chat_id, current_item)
            await self.player.play_next(chat_id)
            if current_item and not await QueueService.get_next_item(chat_id):
                await self._notify_queue_empty(chat_id)

        # Participants list update
        @self.pytgcalls.on(GroupCallAction.PARTICIPANT_LIST_UPDATED)
        @capture_errors
        async def on_participants_updated(gc, _):
            await self._check_empty_chat(gc.chat_id)

        # Network disconnects
        @self.pytgcalls.on(GroupCallAction.NETWORK_STATUS_CHANGED)
        @capture_errors
        async def on_network_status(gc, is_connected: bool):
            if not is_connected:
                logger.warning(f"Disconnected in chat {gc.chat_id}")
                await self._cleanup_chat(gc.chat_id)

        # Kick and leave events still apply
        @self.pytgcalls.on_kicked()
        @capture_errors
        async def on_kicked(_, chat_id: int):
            await self._cleanup_chat(chat_id)
            logger.info(f"Kicked from chat {chat_id}")

        @self.pytgcalls.on_left()
        @capture_errors
        async def on_left(_, chat_id: int):
            await self._cleanup_chat(chat_id)
            logger.info(f"Left chat {chat_id}")

    async def _cleanup_finished_stream(self, chat_id: int, item: QueueItem):
        if item and item.file_path and not item.is_live:
            asyncio.create_task(self._delete_file_with_delay(item.file_path))

    async def _cleanup_chat(self, chat_id: int):
        if chat_id in self.active_chats:
            self.active_chats.remove(chat_id)
            await QueueService.clear_queue(chat_id)
            logger.info(f"Cleaned up chat {chat_id}")

    async def _check_empty_chat(self, chat_id: int):
        try:
            participants = await self.pytgcalls.get_participants(chat_id)
            if not participants:
                logger.info(f"No participants in chat {chat_id}, leaving")
                await self.pytgcalls.leave_group_call(chat_id)
                await self._cleanup_chat(chat_id)
        except Exception as e:
            logger.error(f"Error checking participants: {e}")

    async def _notify_queue_empty(self, chat_id: int):
        from handlers.commands import CommandHandler
        try:
            await CommandHandler.app.send_message(
                chat_id,
                "🎶 Queue is empty. Add more songs with /play!"
            )
        except Exception as e:
            logger.error(f"Error sending message: {e}")

    @staticmethod
    async def _delete_file_with_delay(file_path: str, delay: int = 300):
        await asyncio.sleep(delay)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Deleted file {file_path}")
        except Exception as e:
            logger.error(f"Failed deleting {file_path}: {e}")

    async def is_active_chat(self, chat_id: int) -> bool:
        return chat_id in self.active_chats    
