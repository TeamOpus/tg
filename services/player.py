import asyncio
import logging
from typing import Optional, Dict, Union
import os

from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import AudioPiped
from database.models import QueueItem
from services.queue import QueueService
from utils.downloader import Downloader
from config.config import settings
from utils.helpers import format_duration

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

            if item.file_path:
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
            return True
        except Exception as e:
            logger.error(f"Pause error in chat {chat_id}: {e}")
            return False

    async def resume(self, chat_id: int) -> bool:
        try:
            if chat_id not in self.current_streams:
                return False
            await self.pytgcalls.resume_stream(chat_id)
            return True
        except Exception as e:
            logger.error(f"Resume error in chat {chat_id}: {e}")
            return False

    async def stop(self, chat_id: int) -> bool:
        try:
            await self.pytgcalls.leave_group_call(chat_id)
            await QueueService.clear_queue(chat_id)
            await self._cleanup_chat(chat_id)
            return True
        except Exception as e:
            logger.error(f"Stop error in chat {chat_id}: {e}")
            return False

    async def skip(self, chat_id: int, user_id: int) -> bool:
        try:
            if chat_id not in self.skip_requests:
                self.skip_requests[chat_id] = set()

            self.skip_requests[chat_id].add(user_id)
            participants = await self.pytgcalls.get_participants(chat_id)
            required_votes = max(1, len(participants) // 2)

            if len(self.skip_requests[chat_id]) >= required_votes:
                self.skip_requests[chat_id].clear()
                return await self.play_next(chat_id)

            return False
        except Exception as e:
            logger.error(f"Skip error in chat {chat_id}: {e}")
            return False

    async def set_loop_mode(self, chat_id: int, mode: str) -> bool:
        if mode not in ["none", "single", "queue"]:
            return False
        self.loop_modes[chat_id] = mode
        return True

    async def get_current_item(self, chat_id: int) -> Optional[QueueItem]:
        return self.current_streams.get(chat_id)

    async def get_queue_length(self, chat_id: int) -> int:
        return await QueueService.get_queue_length(chat_id)

    async def is_playing(self, chat_id: int) -> bool:
        return chat_id in self.current_streams

    async def is_paused(self, chat_id: int) -> bool:
        try:
            return await self.pytgcalls.is_paused(chat_id)
        except:
            return False

    async def _cleanup_chat(self, chat_id: int):
        if chat_id in self.current_streams:
            item = self.current_streams.pop(chat_id)
            if item and item.file_path and os.path.exists(item.file_path):
                try:
                    os.remove(item.file_path)
                except Exception as e:
                    logger.error(f"Cleanup error: {e}")
        self.skip_requests.pop(chat_id, None)

    async def _cleanup_file(self, file_path: str, delay: int = 300):
        await asyncio.sleep(delay)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

    def _get_audio_parameters(self, chat_id: int) -> Dict:
        volume = self.volume_levels.get(chat_id, 100) / 100
        return {
            "bitrate": getattr(settings, "AUDIO_BITRATE", 48000),
            "volume": volume,
        }

    async def get_playback_status(self, chat_id: int) -> Dict:
        item = await self.get_current_item(chat_id)
        return {
            "current_item": item.dict() if item else None,
            "is_playing": await self.is_playing(chat_id),
            "is_paused": await self.is_paused(chat_id),
            "queue_length": await self.get_queue_length(chat_id),
            "volume": self.volume_levels.get(chat_id, 100),
            "loop_mode": self.loop_modes.get(chat_id, "none"),
            "skip_votes": len(self.skip_requests.get(chat_id, set())),
                }
