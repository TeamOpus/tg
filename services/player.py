import asyncio
import logging
import os
from typing import Optional, Dict

from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import AudioPiped

from database.models import QueueItem
from services.queue import QueueService
from utils.downloader import Downloader
from utils.helpers import format_duration
from config.config import settings

logger = logging.getLogger(__name__)

class Player:
    def __init__(self, pytgcalls: PyTgCalls):
        self.pytgcalls = pytgcalls
        self.current_streams: Dict[int, QueueItem] = {}
        self.loop_modes: Dict[int, str] = {}
        self.volume_levels: Dict[int, int] = {}
        self.skip_requests: Dict[int, set] = {}

    async def play_next(self, chat_id: int) -> bool:
        try:
            item = await QueueService.get_next_item(chat_id)
            if not item:
                logger.info(f"No items in queue for chat {chat_id}")
                await self._cleanup_chat(chat_id)
                return False

            if not item.file_path:
                file_path, duration = await Downloader.download_media(item.url)
                if not file_path:
                    logger.error(f"Failed to download media for {item.url}")
                    return await self.play_next(chat_id)
                item.file_path = file_path
                if duration:
                    item.duration = duration

            stream = AudioPiped(item.file_path)

            self.current_streams[chat_id] = item
            await self.pytgcalls.join_group_call(chat_id, stream)
            logger.info(f"Started playing {item.title} in chat {chat_id}")

            asyncio.create_task(self._cleanup_file(item.file_path))
            return True

        except Exception as e:
            logger.error(f"Error playing next item in chat {chat_id}: {e}")
            return await self.play_next(chat_id)

    async def pause(self, chat_id: int) -> bool:
        try:
            if chat_id not in self.current_streams:
                return False
            await self.pytgcalls.pause_stream(chat_id)
            logger.info(f"Paused playback in chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error pausing: {e}")
            return False

    async def resume(self, chat_id: int) -> bool:
        try:
            if chat_id not in self.current_streams:
                return False
            await self.pytgcalls.resume_stream(chat_id)
            logger.info(f"Resumed playback in chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error resuming: {e}")
            return False

    async def stop(self, chat_id: int) -> bool:
        try:
            await self.pytgcalls.leave_group_call(chat_id)
            await QueueService.clear_queue(chat_id)
            await self._cleanup_chat(chat_id)
            logger.info(f"Stopped playback in chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error stopping: {e}")
            return False

    async def skip(self, chat_id: int, user_id: int) -> bool:
        try:
            self.skip_requests.setdefault(chat_id, set()).add(user_id)
            participants = await self.pytgcalls.get_participants(chat_id)
            required_votes = max(1, len(participants) // 2)

            if len(self.skip_requests[chat_id]) >= required_votes:
                self.skip_requests[chat_id].clear()
                return await self.play_next(chat_id)

            return False
        except Exception as e:
            logger.error(f"Error skipping: {e}")
            return False

    async def set_volume(self, chat_id: int, volume: int) -> bool:
        try:
            volume = max(0, min(200, volume))
            self.volume_levels[chat_id] = volume
            logger.info(f"Volume set to {volume} for chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error setting volume: {e}")
            return False

    async def set_loop_mode(self, chat_id: int, mode: str) -> bool:
        if mode not in ["none", "single", "queue"]:
            return False
        self.loop_modes[chat_id] = mode
        logger.info(f"Loop mode set to {mode} for chat {chat_id}")
        return True

    async def is_paused(self, chat_id: int) -> bool:
        try:
            return await self.pytgcalls.is_paused(chat_id)
        except:
            return False

    async def is_playing(self, chat_id: int) -> bool:
        return chat_id in self.current_streams

    async def get_current_item(self, chat_id: int) -> Optional[QueueItem]:
        return self.current_streams.get(chat_id)

    async def get_queue_length(self, chat_id: int) -> int:
        return await QueueService.get_queue_length(chat_id)

    async def get_playback_status(self, chat_id: int) -> Dict:
        item = await self.get_current_item(chat_id)
        return {
            "current_item": item.dict() if item else None,
            "is_playing": await self.is_playing(chat_id),
            "is_paused": await self.is_paused(chat_id),
            "queue_length": await self.get_queue_length(chat_id),
            "volume": self.volume_levels.get(chat_id, 100),
            "loop_mode": self.loop_modes.get(chat_id, "none"),
            "skip_votes": len(self.skip_requests.get(chat_id, set()))
        }

    async def _cleanup_chat(self, chat_id: int):
        if chat_id in self.current_streams:
            item = self.current_streams.pop(chat_id)
            if item.file_path and os.path.exists(item.file_path):
                try:
                    os.remove(item.file_path)
                except Exception as e:
                    logger.error(f"File cleanup error: {e}")
        self.skip_requests.pop(chat_id, None)

    async def _cleanup_file(self, file_path: str, delay: int = 300):
        await asyncio.sleep(delay)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            logger.error(f"File cleanup error: {e}")
