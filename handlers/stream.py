import asyncio
import logging
import os

from pytgcalls import PyTgCalls
from pytgcalls.types.stream import StreamAudioEnded
from pytgcalls.types.input_stream import AudioPiped, AudioVideoPiped
from pytgcalls.types.input_stream.quality import HighQualityAudio, HighQualityVideo

from services.player import Player
from services.queue import QueueService
from utils.decorators import capture_errors
from database.models import QueueItem

logger = logging.getLogger(__name__)

class StreamHandler:
    def __init__(self, pytgcalls: PyTgCalls, player: Player):
        self.pytgcalls = pytgcalls
        self.player = player
        self.active_chats = set()
        self.register_handlers()

    def register_handlers(self):
        @self.pytgcalls.on_stream_end()
        @capture_errors
        async def on_stream_end(_, update: StreamAudioEnded):
            chat_id = update.chat_id
            logger.info(f"Playback ended in chat {chat_id}")
            current_item = await QueueService.get_current_item(chat_id)
            await self._cleanup_finished_stream(chat_id, current_item)
            await self.player.play_next(chat_id)
            if current_item and not await QueueService.get_next_item(chat_id):
                await self._notify_queue_empty(chat_id)

    async def join_call(self, chat_id: int, file_path: str, video: bool = False):
        try:
            stream = (
                AudioVideoPiped(file_path, HighQualityAudio(), HighQualityVideo())
                if video else
                AudioPiped(file_path, HighQualityAudio())
            )
            await self.pytgcalls.join_group_call(chat_id, stream)
            self.active_chats.add(chat_id)
            logger.info(f"🎧 Stream started in chat {chat_id} with file: {file_path}")
        except Exception as e:
            logger.error(f"Failed to join call in chat {chat_id}: {e}")

    async def leave_call(self, chat_id: int):
        try:
            await self.pytgcalls.leave_group_call(chat_id)
            self.active_chats.discard(chat_id)
            await QueueService.clear_queue(chat_id)
            logger.info(f"Left VC and cleared queue for chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to leave call in chat {chat_id}: {e}")

    async def _cleanup_finished_stream(self, chat_id: int, item: QueueItem):
        if item and item.file_path and not item.is_live:
            asyncio.create_task(self._delete_file_with_delay(item.file_path))

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
