from pyrogram import filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import BadRequest
from database.models import QueueItem
from services.queue import QueueService
from services.player import Player
from utils.helpers import format_duration
from utils.decorators import capture_errors
from config.config import settings
import logging

logger = logging.getLogger(__name__)

class CallbackHandler:
    def __init__(self, app, pytgcalls, player):
        self.app = app
        self.pytgcalls = pytgcalls
        self.player = player
        self.register_handlers()

    def register_handlers(self):
        @self.app.on_callback_query(filters.regex(r"^player_"))
        @capture_errors
        async def player_controls(_, callback: CallbackQuery):
            action = callback.data.split("_")[1]
            chat_id = callback.message.chat.id
            
            if action == "pause":
                await self.pytgcalls.pause_stream(chat_id)
                await callback.answer("⏸ Playback paused")
                await self._update_control_buttons(callback)
                
            elif action == "resume":
                await self.pytgcalls.resume_stream(chat_id)
                await callback.answer("▶️ Playback resumed")
                await self._update_control_buttons(callback)
                
            elif action == "skip":
                await self.player.play_next(chat_id)
                await callback.answer("⏭ Skipped to next track")
                await callback.message.delete()
                
            elif action == "stop":
                await self.pytgcalls.leave_call(chat_id)
                await QueueService.clear_queue(chat_id)
                await callback.answer("⏹ Playback stopped")
                await callback.message.delete()
                
            elif action == "loop":
                # Implement loop logic here
                await callback.answer("🔁 Loop mode changed")

        @self.app.on_callback_query(filters.regex(r"^queue_"))
        @capture_errors
        async def queue_controls(_, callback: CallbackQuery):
            action, *args = callback.data.split("_")[1:]
            chat_id = callback.message.chat.id
            
            if action == "view":
                page = int(args[0]) if args else 1
                await self._show_queue_page(callback, chat_id, page)
                
            elif action == "remove":
                position = int(args[0])
                removed = await QueueService.remove_queue_item(chat_id, position)
                if removed:
                    await callback.answer("🗑 Item removed from queue")
                    await self._show_queue_page(callback, chat_id, 1)
                else:
                    await callback.answer("❌ Invalid position", show_alert=True)

        @self.app.on_callback_query(filters.regex(r"^close$"))
        @capture_errors
        async def close_menu(_, callback: CallbackQuery):
            await callback.message.delete()
            await callback.answer()

    async def _update_control_buttons(self, callback: CallbackQuery):
        try:
            is_paused = await self.pytgcalls.is_paused(callback.message.chat.id)
            
            buttons = [
                [
                    InlineKeyboardButton("⏸ Pause" if not is_paused else "▶️ Resume", 
                                       callback_data=f"player_{'pause' if not is_paused else 'resume'}"),
                    InlineKeyboardButton("⏭ Skip", callback_data="player_skip"),
                    InlineKeyboardButton("⏹ Stop", callback_data="player_stop")
                ],
                [
                    InlineKeyboardButton("🔁 Loop", callback_data="player_loop"),
                    InlineKeyboardButton("📋 Queue", callback_data="queue_view_1"),
                    InlineKeyboardButton("❌ Close", callback_data="close")
                ]
            ]
            
            await callback.message.edit_reply_markup(
                InlineKeyboardMarkup(buttons)
            )
        except BadRequest as e:
            logger.warning(f"Button update failed: {e}")

    async def _show_queue_page(self, callback: CallbackQuery, chat_id: int, page: int):
        items = await QueueService.get_queue(chat_id)
        items_per_page = 5
        total_pages = (len(items) + items_per_page - 1) // items_per_page
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * items_per_page
        page_items = items[start_idx:start_idx + items_per_page]
        
        text = "**Current Queue**\n\n"
        for idx, item in enumerate(page_items, start=start_idx + 1):
            text += f"{idx}. {item.title} - `{item.formatted_duration}`\n"
        
        if total_pages > 1:
            text += f"\nPage {page}/{total_pages}"
        
        buttons = []
        if len(page_items) > 0:
            buttons.append([
                InlineKeyboardButton("🗑 Remove", callback_data=f"queue_remove_{start_idx + 1}")
            ])
        
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"queue_view_{page - 1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"queue_view_{page + 1}"))
        
        if nav_buttons:
            buttons.append(nav_buttons)
        
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="player_controls")])
        
        try:
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            await callback.answer()
        except BadRequest as e:
            logger.warning(f"Queue display failed: {e}")
            await callback.answer("Queue is empty", show_alert=True)

    @staticmethod
    def get_player_controls():
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("⏸ Pause", callback_data="player_pause"),
                    InlineKeyboardButton("⏭ Skip", callback_data="player_skip"),
                    InlineKeyboardButton("⏹ Stop", callback_data="player_stop")
                ],
                [
                    InlineKeyboardButton("🔁 Loop", callback_data="player_loop"),
                    InlineKeyboardButton("📋 Queue", callback_data="queue_view_1"),
                    InlineKeyboardButton("❌ Close", callback_data="close")
                ]
            ]
        )

    @staticmethod
    def get_queue_controls(page: int = 1, total_pages: int = 1):
        buttons = []
        
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"queue_view_{page - 1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"queue_view_{page + 1}"))
        
        if nav_buttons:
            buttons.append(nav_buttons)
        
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="player_controls")])
        
        return InlineKeyboardMarkup(buttons)
    
