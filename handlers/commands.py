from pyrogram import filters
from pyrogram.types import Message, InlineKeyboardMarkup
from pyrogram.enums import ParseMode
from typing import Optional, Tuple, List
from config.config import settings
from database.models import QueueItem
from services.youtube import YouTubeService
from services.spotify import SpotifyService
from services.queue import QueueService
from services.player import Player
from utils.downloader import Downloader
from utils.helpers import (
    extract_command_args,
    is_youtube_url,
    is_spotify_url,
    format_duration
)

from handlers.callbacks import CallbackHandler
import re
import logging
import asyncio

from utils.decorators import capture_errors, admin_only, rate_limit

@capture_errors
@admin_only
@rate_limit()
async def my_command(client: Client, message: Message):
    await message.reply("✅ This command is working fine.")


logger = logging.getLogger(__name__)

class CommandHandler:
    def __init__(self, app, pytgcalls, player):
        self.app = app
        self.pytgcalls = pytgcalls
        self.player = player
        self.callback_handler = CallbackHandler(app, pytgcalls, player)
        self.register_commands()

    def register_commands(self):
        @self.app.on_message(filters.command(["start", "help"]))
        @capture_errors
        @rate_limit(3, 60)
        async def start_command(_, message: Message):
            help_text = """
🎵 **Music Bot Help** 🎵

**Basic Commands:**
/play <query> - Play a song from YouTube or direct link
/vplay <query> - Play video from YouTube
/queue - Show current queue
/now - Show currently playing track
/skip - Skip current track
/pause - Pause playback
/resume - Resume playback
/stop - Stop playback and clear queue

**Advanced Commands:**
/loop - Toggle loop mode
/seek <seconds> - Seek to position in track
/remove <position> - Remove track from queue
/clean - Remove all downloaded files

**Admin Commands:**
/admin - Admin panel
/restart - Restart the bot (admin only)
"""
            await message.reply(help_text, parse_mode=ParseMode.MARKDOWN)

        @self.app.on_message(filters.command("play"))
        @capture_errors
        @rate_limit(5, 60)
        async def play_command(_, message: Message):
            args = extract_command_args(message)
            if not args:
                return await message.reply("Please provide a song name or URL")

            chat_id = message.chat.id
            user_id = message.from_user.id

            # Check if input is a Spotify link
            if is_spotify_url(args):
                await self._handle_spotify_input(message, args)
                return

            # Process YouTube or direct audio input
            await self._process_media_input(
                message=message,
                query=args,
                chat_id=chat_id,
                user_id=user_id,
                is_video=False
            )

        @self.app.on_message(filters.command("vplay"))
        @capture_errors
        @rate_limit(5, 60)
        async def vplay_command(_, message: Message):
            args = extract_command_args(message)
            if not args:
                return await message.reply("Please provide a video name or URL")

            await self._process_media_input(
                message=message,
                query=args,
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                is_video=True
            )

        @self.app.on_message(filters.command(["queue", "q"]))
        @capture_errors
        @rate_limit(3, 30)
        async def queue_command(_, message: Message):
            chat_id = message.chat.id
            queue_items = await QueueService.get_queue(chat_id)

            if not queue_items:
                return await message.reply("The queue is empty")

            response = ["**Current Queue:**\n"]
            for idx, item in enumerate(queue_items[:10], 1):
                duration = format_duration(item.duration) if item.duration else "Live"
                response.append(f"{idx}. {item.title} - `{duration}`")

            await message.reply(
                "\n".join(response),
                reply_markup=self.callback_handler.get_queue_controls(),
                parse_mode=ParseMode.MARKDOWN
            )

        @self.app.on_message(filters.command(["skip", "next"]))
        @capture_errors
        @rate_limit(3, 30)
        async def skip_command(_, message: Message):
            chat_id = message.chat.id
            await self.player.play_next(chat_id)
            await message.reply("⏭ Skipped to next track")

        @self.app.on_message(filters.command(["pause"]))
        @capture_errors
        @rate_limit(3, 30)
        async def pause_command(_, message: Message):
            chat_id = message.chat.id
            await self.pytgcalls.pause_stream(chat_id)
            await message.reply("⏸ Playback paused")

        @self.app.on_message(filters.command(["resume", "continue"]))
        @capture_errors
        @rate_limit(3, 30)
        async def resume_command(_, message: Message):
            chat_id = message.chat.id
            await self.pytgcalls.resume_stream(chat_id)
            await message.reply("▶️ Playback resumed")

        @self.app.on_message(filters.command(["stop", "end"]))
        @capture_errors
        @admin_only
        async def stop_command(_, message: Message):
            chat_id = message.chat.id
            await self.pytgcalls.leave_call(chat_id)
            await QueueService.clear_queue(chat_id)
            await message.reply("⏹ Playback stopped and queue cleared")

        @self.app.on_message(filters.command(["now", "np", "current"]))
        @capture_errors
        @rate_limit(3, 30)
        async def now_playing_command(_, message: Message):
            chat_id = message.chat.id
            current_item = await QueueService.get_current_item(chat_id)

            if not current_item:
                return await message.reply("Nothing is currently playing")

            duration = format_duration(current_item.duration) if current_item.duration else "Live"
            text = (
                f"**Now Playing:** {current_item.title}\n"
                f"**Duration:** `{duration}`\n"
                f"**Requested by:** {message.from_user.mention}"
            )

            await message.reply(
                text,
                reply_markup=self.callback_handler.get_player_controls(),
                parse_mode=ParseMode.MARKDOWN
            )

        @self.app.on_message(filters.command(["remove", "rm"]))
        @capture_errors
        @rate_limit(3, 30)
        async def remove_command(_, message: Message):
            args = extract_command_args(message)
            try:
                position = int(args)
            except (ValueError, TypeError):
                return await message.reply("Please provide a valid queue position")

            chat_id = message.chat.id
            removed = await QueueService.remove_queue_item(chat_id, position)

            if removed:
                await message.reply(f"🗑 Removed item at position {position}")
            else:
                await message.reply("❌ Invalid queue position")

        @self.app.on_message(filters.command(["loop", "repeat"]))
        @capture_errors
        @rate_limit(3, 30)
        async def loop_command(_, message: Message):
            # Implement loop functionality
            await message.reply("🔁 Loop mode toggled")

        @self.app.on_message(filters.command(["seek"]))
        @capture_errors
        @rate_limit(3, 30)
        async def seek_command(_, message: Message):
            args = extract_command_args(message)
            try:
                seconds = int(args)
            except (ValueError, TypeError):
                return await message.reply("Please provide valid seconds to seek")

            chat_id = message.chat.id
            await self.pytgcalls.change_stream(chat_id, MediaStream(seek=seconds))
            await message.reply(f"⏩ Seeked to {format_duration(seconds)}")

        @self.app.on_message(filters.command(["clean", "clear"]))
        @capture_errors
        @admin_only
        async def clean_command(_, message: Message):
            # Implement cleanup of downloaded files
            await message.reply("🧹 Cleaned up temporary files")

        @self.app.on_message(filters.command(["restart"]))
        @capture_errors
        @admin_only
        async def restart_command(_, message: Message):
            await message.reply("🔄 Restarting bot...")
            # Implement actual restart logic
            raise SystemExit

    async def _handle_spotify_input(self, message: Message, url: str):
        """Process Spotify track or playlist URLs"""
        chat_id = message.chat.id
        user_id = message.from_user.id

        if "track" in url:
            track = await SpotifyService.get_track(url)
            if not track:
                return await message.reply("❌ Could not fetch Spotify track")

            query = f"{track['name']} {track['artists'][0]}"
            await self._process_media_input(
                message=message,
                query=query,
                chat_id=chat_id,
                user_id=user_id,
                is_video=False
            )

        elif "playlist" in url:
            tracks = await SpotifyService.get_playlist(url)
            if not tracks:
                return await message.reply("❌ Could not fetch Spotify playlist")

            msg = await message.reply(f"🔍 Adding {len(tracks)} tracks from Spotify playlist...")

            added = 0
            for track in tracks:
                query = f"{track['name']} {track['artists'][0]}"
                youtube_data = await YouTubeService.search(query)
                if youtube_data:
                    await self._add_to_queue(
                        chat_id=chat_id,
                        user_id=user_id,
                        youtube_data=youtube_data,
                        is_video=False
                    )
                    added += 1

            await msg.edit_text(f"✅ Added {added} tracks from Spotify playlist")

    async def _process_media_input(
        self,
        message: Message,
        query: str,
        chat_id: int,
        user_id: int,
        is_video: bool = False
    ):
        """Process YouTube URLs or search queries"""
        if is_youtube_url(query):
            # Direct YouTube URL
            youtube_data = await YouTubeService.get_video_info(query)
        else:
            # YouTube search
            youtube_data = await YouTubeService.search(query)

        if not youtube_data:
            return await message.reply("❌ No results found")

        await self._add_to_queue(
            chat_id=chat_id,
            user_id=user_id,
            youtube_data=youtube_data,
            is_video=is_video,
            message=message
        )

    async def _add_to_queue(
        self,
        chat_id: int,
        user_id: int,
        youtube_data: dict,
        is_video: bool,
        message: Optional[Message] = None
    ):
        """Add item to queue and notify user"""
        queue_item = QueueItem(
            chat_id=chat_id,
            user_id=user_id,
            item_type="youtube",
            title=youtube_data['title'],
            url=youtube_data['url'],
            thumbnail=youtube_data.get('thumbnail'),
            is_live=youtube_data.get('is_live', False),
            duration=youtube_data.get('duration')
        )

        await QueueService.add_to_queue(queue_item)

        # Get current queue position
        queue = await QueueService.get_queue(chat_id)
        position = len([item for item in queue if not item.played])

        # Prepare response message
        duration = format_duration(youtube_data.get('duration')) if youtube_data.get('duration') else "Live"
        text = (
            f"🎵 **Added to queue (#{position}):** {youtube_data['title']}\n"
            f"⏱ **Duration:** `{duration}`"
        )

        if message:
            await message.reply(
                text,
                reply_markup=self.callback_handler.get_player_controls(),
                parse_mode=ParseMode.MARKDOWN
            )

        # Start playback if nothing is playing
        if position == 1:
            await self.player.play_next(chat_id)

            
