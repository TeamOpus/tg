import asyncio
import logging
from typing import Optional, Dict, Union
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
from database.models import QueueItem
from services.queue import QueueService
from utils.downloader import Downloader
from utils.helpers import format_duration
from config.config import settings
import os

logger = logging.getLogger(__name__)

class Player:
    def __init__(self, pytgcalls: PyTgCalls):
        self.pytgcalls = pytgcalls
        self.current_streams: Dict[int, QueueItem] = {}  # chat_id: current_item
        self.loop_modes: Dict[int, str] = {}  # chat_id: loop_mode ("none", "single", "queue")
        self.volume_levels: Dict[int, int] = {}  # chat_id: volume (0-200)
        self.skip_requests: Dict[int, set] = {}  # chat_id: set of user_ids who voted to skip

    async def play_next(self, chat_id: int) -> bool:
        """Play the next item in the queue"""
        try:
            # Get the next item from queue
            item = await QueueService.get_next_item(chat_id)
            if not item:
                logger.info(f"No items in queue for chat {chat_id}")
                await self._cleanup_chat(chat_id)
                return False

            # Handle different media types
            if item.is_live:
                stream = MediaStream(item.url)
            else:
                if not item.file_path:
                    # Download if not already downloaded
                    file_path, duration = await Downloader.download_media(item.url)
                    if not file_path:
                        logger.error(f"Failed to download media for {item.url}")
                        return await self.play_next(chat_id)  # Skip to next
                    item.file_path = file_path
                    if duration:
                        item.duration = duration

                stream = MediaStream(
                    item.file_path,
                    audio_parameters=self._get_audio_parameters(chat_id)
                )

            # Store current stream
            self.current_streams[chat_id] = item

            # Start playback
            await self.pytgcalls.play(chat_id, stream)
            logger.info(f"Started playing {item.title} in chat {chat_id}")

            # Schedule cleanup if not live stream
            if not item.is_live and item.file_path:
                asyncio.create_task(self._cleanup_file(item.file_path))

            return True

        except Exception as e:
            logger.error(f"Error playing next item in chat {chat_id}: {e}")
            return await self.play_next(chat_id)  # Try next item on error

    async def pause(self, chat_id: int) -> bool:
        """Pause current playback"""
        try:
            if chat_id not in self.current_streams:
                return False

            await self.pytgcalls.pause_stream(chat_id)
            logger.info(f"Paused playback in chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error pausing playback in chat {chat_id}: {e}")
            return False

    async def resume(self, chat_id: int) -> bool:
        """Resume paused playback"""
        try:
            if chat_id not in self.current_streams:
                return False

            await self.pytgcalls.resume_stream(chat_id)
            logger.info(f"Resumed playback in chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error resuming playback in chat {chat_id}: {e}")
            return False

    async def stop(self, chat_id: int) -> bool:
        """Stop playback and clear queue"""
        try:
            await self.pytgcalls.leave_call(chat_id)
            await QueueService.clear_queue(chat_id)
            await self._cleanup_chat(chat_id)
            logger.info(f"Stopped playback in chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error stopping playback in chat {chat_id}: {e}")
            return False

    async def skip(self, chat_id: int, user_id: int) -> bool:
        """Skip current track (with vote system)"""
        try:
            # Initialize skip requests set if needed
            if chat_id not in self.skip_requests:
                self.skip_requests[chat_id] = set()

            # Add user to skip votes
            self.skip_requests[chat_id].add(user_id)

            # Get current participants
            participants = await self.pytgcalls.get_participants(chat_id)
            required_votes = max(1, len(participants) // 2)  # 50% + 1

            if len(self.skip_requests[chat_id]) >= required_votes:
                # Enough votes to skip
                self.skip_requests[chat_id].clear()
                return await self.play_next(chat_id)
            
            return False
        except Exception as e:
            logger.error(f"Error processing skip in chat {chat_id}: {e}")
            return False

    async def seek(self, chat_id: int, seconds: int) -> bool:
        """Seek to position in current track"""
        try:
            if chat_id not in self.current_streams:
                return False

            item = self.current_streams[chat_id]
            if item.is_live:
                return False  # Can't seek in live streams

            await self.pytgcalls.change_stream(
                chat_id,
                MediaStream(
                    item.file_path,
                    seek=seconds,
                    audio_parameters=self._get_audio_parameters(chat_id)
                )
            )
            logger.info(f"Seeked to {seconds}s in chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error seeking in chat {chat_id}: {e}")
            return False

    async def set_volume(self, chat_id: int, volume: int) -> bool:
        """Set playback volume (0-200)"""
        try:
            volume = max(0, min(200, volume))  # Clamp to 0-200
            self.volume_levels[chat_id] = volume

            if chat_id in self.current_streams:
                item = self.current_streams[chat_id]
                if not item.is_live:
                    await self.pytgcalls.change_stream(
                        chat_id,
                        MediaStream(
                            item.file_path,
                            audio_parameters=self._get_audio_parameters(chat_id)
                        )
                    )
            
            logger.info(f"Set volume to {volume}% in chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error setting volume in chat {chat_id}: {e}")
            return False

    async def set_loop_mode(self, chat_id: int, mode: str) -> bool:
        """Set loop mode ('none', 'single', 'queue')"""
        if mode not in ['none', 'single', 'queue']:
            return False

        self.loop_modes[chat_id] = mode
        logger.info(f"Set loop mode to {mode} in chat {chat_id}")
        return True

    async def get_current_item(self, chat_id: int) -> Optional[QueueItem]:
        """Get currently playing item"""
        return self.current_streams.get(chat_id)

    async def get_queue_length(self, chat_id: int) -> int:
        """Get number of items in queue"""
        return await QueueService.get_queue_length(chat_id)

    async def is_playing(self, chat_id: int) -> bool:
        """Check if currently playing"""
        return chat_id in self.current_streams

    async def is_paused(self, chat_id: int) -> bool:
        """Check if currently paused"""
        try:
            return await self.pytgcalls.is_paused(chat_id)
        except:
            return False

    async def _cleanup_chat(self, chat_id: int):
        """Clean up resources when leaving a chat"""
        if chat_id in self.current_streams:
            item = self.current_streams.pop(chat_id)
            if item and item.file_path and os.path.exists(item.file_path):
                try:
                    os.remove(item.file_path)
                    logger.info(f"Cleaned up file: {item.file_path}")
                except Exception as e:
                    logger.error(f"Error cleaning up file {item.file_path}: {e}")

        if chat_id in self.skip_requests:
            self.skip_requests.pop(chat_id)

    async def _cleanup_file(self, file_path: str, delay: int = 300):
        """Delete file after delay if it exists"""
        await asyncio.sleep(delay)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up file: {file_path}")
        except Exception as e:
            logger.error(f"Error cleaning up file {file_path}: {e}")

    def _get_audio_parameters(self, chat_id: int) -> Dict:
        """Get audio parameters including volume"""
        volume = self.volume_levels.get(chat_id, 100) / 100  # Convert to 0.0-2.0 range
        return {
            'bitrate': settings.AUDIO_BITRATE if hasattr(settings, 'AUDIO_BITRATE') else 48000,
            'volume': volume
        }

    async def get_playback_status(self, chat_id: int) -> Dict:
        """Get complete playback status"""
        item = await self.get_current_item(chat_id)
        queue_length = await self.get_queue_length(chat_id)
        is_playing = await self.is_playing(chat_id)
        is_paused = await self.is_paused(chat_id)
        volume = self.volume_levels.get(chat_id, 100)
        loop_mode = self.loop_modes.get(chat_id, 'none')

        return {
            'current_item': item.dict() if item else None,
            'is_playing': is_playing,
            'is_paused': is_paused,
            'queue_length': queue_length,
            'volume': volume,
            'loop_mode': loop_mode,
            'skip_votes': len(self.skip_requests.get(chat_id, set()))
        }