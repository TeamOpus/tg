import re
import time
import random
import asyncio
import logging
from typing import Optional, Union, List, Dict, Tuple
from datetime import timedelta
from pyrogram.types import Message, CallbackQuery
from config.config import settings
import math
import string
import urllib.parse
import mimetypes

logger = logging.getLogger(__name__)

# ---------------------------
# Text Formatting Helpers
# ---------------------------

def format_duration(seconds: Union[int, float]) -> str:
    """Format duration in seconds to HH:MM:SS or MM:SS"""
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"

def format_file_size(bytes: int) -> str:
    """Convert bytes to human-readable file size"""
    if bytes == 0:
        return "0B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(bytes, 1024)))
    size = round(bytes / math.pow(1024, i), 2)
    return f"{size}{units[i]}"

def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text with ellipsis if too long"""
    return (text[:max_length] + '...') if len(text) > max_length else text

def escape_markdown(text: str) -> str:
    """Escape special Markdown characters"""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

# ---------------------------
# URL and Link Helpers
# ---------------------------

def is_youtube_url(url: str) -> bool:
    """Check if string is a YouTube URL"""
    patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=[\w-]+',
        r'(?:https?://)?(?:www\.)?youtu\.be/[\w-]+',
        r'(?:https?://)?(?:www\.)?youtube\.com/live/[\w-]+',
        r'(?:https?://)?(?:www\.)?music\.youtube\.com/watch\?v=[\w-]+'
    ]
    return any(re.match(pattern, url) for pattern in patterns)

def is_spotify_url(url: str) -> bool:
    """Check if string is a Spotify URL"""
    patterns = [
        r'(?:https?://)?open\.spotify\.com/track/[\w]+',
        r'(?:https?://)?open\.spotify\.com/playlist/[\w]+',
        r'(?:https?://)?open\.spotify\.com/album/[\w]+',
        r'spotify:track:[\w]+',
        r'spotify:playlist:[\w]+',
        r'spotify:album:[\w]+'
    ]
    return any(re.match(pattern, url) for pattern in patterns)

def extract_command_args(message: Message) -> str:
    """Extract arguments from command message"""
    if not (message.text or message.caption):
        return ""
    
    text = message.text or message.caption
    split = text.split(maxsplit=1)
    return split[1] if len(split) > 1 else ""

def parse_time_string(time_str: str) -> Optional[int]:
    """Parse time string (e.g. 1:30, 90s) into seconds"""
    try:
        if ':' in time_str:
            parts = time_str.split(':')
            if len(parts) == 2:  # MM:SS
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:  # HH:MM:SS
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif time_str.endswith('s'):
            return int(time_str[:-1])
        elif time_str.endswith('m'):
            return int(time_str[:-1]) * 60
        elif time_str.endswith('h'):
            return int(time_str[:-1]) * 3600
        else:
            return int(time_str)
    except (ValueError, AttributeError):
        return None

# ---------------------------
# Media and File Helpers
# ---------------------------

def get_file_extension(url: str) -> Optional[str]:
    """Get file extension from URL"""
    path = urllib.parse.urlparse(url).path
    return path.split('.')[-1].lower() if '.' in path else None

def is_audio_file(filename: str) -> bool:
    """Check if file is an audio file by extension"""
    audio_extensions = ['.mp3', '.ogg', '.wav', '.m4a', '.flac', '.opus']
    return any(filename.lower().endswith(ext) for ext in audio_extensions)

def is_video_file(filename: str) -> bool:
    """Check if file is a video file by extension"""
    video_extensions = ['.mp4', '.mkv', '.webm', '.mov', '.avi', '.flv']
    return any(filename.lower().endswith(ext) for ext in video_extensions)

def guess_mime_type(filename: str) -> str:
    """Guess MIME type from filename"""
    return mimetypes.guess_type(filename)[0] or 'application/octet-stream'

# ---------------------------
# User and Chat Helpers
# ---------------------------

def mention_user(user_id: int, name: str) -> str:
    """Create a user mention string"""
    return f"[{name}](tg://user?id={user_id})"

def extract_user_ids(text: str) -> List[int]:
    """Extract user IDs from text mentions"""
    return [int(match.group(1)) for match in re.finditer(r'tg://user\?id=(\d+)', text)]

def is_admin(chat_id: int, user_id: int) -> bool:
    """Check if user is admin in chat (placeholder - implement with actual check)"""
    # This should be replaced with actual Telegram API check
    return user_id in settings.ADMINS if hasattr(settings, 'ADMINS') else False

# ---------------------------
# Random Generation Helpers
# ---------------------------

def random_string(length: int = 8) -> str:
    """Generate random alphanumeric string"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def error_emoji() -> str:
    """Get a random error emoji"""
    emojis = ["❌", "⚠️", "🚫", "⛔", "🔴", "💢"]
    return random.choice(emojis)

def music_emoji() -> str:
    """Get a random music emoji"""
    emojis = ["🎵", "🎶", "🎧", "🎼", "🎤", "🎹", "🥁", "🎷", "🎺", "🎸"]
    return random.choice(emojis)

# ---------------------------
# Async and Timing Helpers
# ---------------------------

async def async_retry(func, max_retries: int = 3, delay: float = 1.0, **kwargs):
    """Retry async function with exponential backoff"""
    for attempt in range(max_retries):
        try:
            return await func(**kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait_time = delay * (2 ** attempt)
            logger.warning(f"Attempt {attempt + 1} failed. Retrying in {wait_time}s...")
            await asyncio.sleep(wait_time)

class Timer:
    """Context manager for timing code blocks"""
    def __enter__(self):
        self.start = time.time()
        return self
    
    def __exit__(self, *args):
        self.end = time.time()
        self.elapsed = self.end - self.start
    
    def __str__(self):
        return f"{self.elapsed:.2f}s"

# ---------------------------
# Text Processing Helpers
# ---------------------------

def parse_search_query(query: str) -> Dict[str, str]:
    """Parse search query with optional filters"""
    # Example: "artist:Queen title:Bohemian Rhapsody year:1975"
    filters = {}
    remaining = []
    
    for part in query.split():
        if ':' in part:
            key, value = part.split(':', 1)
            filters[key.lower()] = value
        else:
            remaining.append(part)
    
    return {
        'filters': filters,
        'query': ' '.join(remaining) if remaining else None
    }

def split_text(text: str, max_length: int = 4000) -> List[str]:
    """Split long text into chunks that fit Telegram message limits"""
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    while text:
        chunk = text[:max_length]
        last_newline = chunk.rfind('\n')
        if last_newline > 0 and len(chunk) == max_length:
            chunk = chunk[:last_newline]
        chunks.append(chunk)
        text = text[len(chunk):].lstrip()
    
    return chunks

# ---------------------------
# Formatting Presets
# ---------------------------

def format_song_info(title: str, artist: str, duration: int = None) -> str:
    """Format song information consistently"""
    duration_str = f" - {format_duration(duration)}" if duration else ""
    return f"🎵 {escape_markdown(title)} by {escape_markdown(artist)}{duration_str}"

def format_queue_position(position: int, total: int) -> str:
    """Format queue position information"""
    return f"#{position} of {total}"

def format_progress_bar(current: int, total: int, length: int = 20) -> str:
    """Create a progress bar string"""
    progress = min(current / total, 1.0)
    filled = round(progress * length)
    return f"[{'█' * filled}{'░' * (length - filled)}] {progress * 100:.1f}%"

# ---------------------------
# Validation Helpers
# ---------------------------

def is_valid_url(url: str) -> bool:
    """Check if string is a valid URL"""
    try:
        result = urllib.parse.urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False

def is_valid_timecode(time_str: str) -> bool:
    """Check if string is a valid time format (HH:MM:SS, MM:SS, or seconds)"""
    patterns = [
        r'^\d+:\d{2}:\d{2}$',  # HH:MM:SS
        r'^\d+:\d{2}$',         # MM:SS
        r'^\d+[hms]?$'          # 123, 123s, 123m, 123h
    ]
    return any(re.match(pattern, time_str) for pattern in patterns)

# ---------------------------
# Message Formatting Helpers
# ---------------------------

async def reply_or_edit(
    message: Union[Message, CallbackQuery],
    text: str,
    **kwargs
) -> Message:
    """Reply to message or edit callback query"""
    if isinstance(message, CallbackQuery):
        await message.answer()
        return await message.message.reply(text, **kwargs)
    return await message.reply(text, **kwargs)

def create_inline_keyboard(buttons: List[List[Dict[str, str]]]) -> Dict:
    """Create inline keyboard markup from button matrix"""
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(btn['text'], callback_data=btn['data'])]
            for row in buttons for btn in row
        ]
    )

# ---------------------------
# Debugging Helpers
# ---------------------------

def log_exception(e: Exception, context: str = None):
    """Log exception with context"""
    logger.error(f"Exception in {context or 'unknown context'}: {str(e)}")
    logger.error(f"Traceback: {traceback.format_exc()}")

def pretty_print(data: Union[Dict, List], indent: int = 4) -> str:
    """Format data structure for readable logging"""
    return json.dumps(data, indent=indent, ensure_ascii=False)
