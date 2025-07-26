import re
import asyncio
import logging
from typing import Optional, Dict, List, Tuple
from yt_dlp import YoutubeDL
from urllib.parse import parse_qs, urlparse
from config.config import settings
from utils.ip_rotator import IPRotator
from utils.helpers import format_duration
from utils.downloader import Downloader
import json

logger = logging.getLogger(__name__)

class YouTubeService:
    def __init__(self):
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'force_ipv4': True,
            'socket_timeout': 30,
            'extract_flat': 'in_playlist',
        }
        self.max_retries = 3
        self.retry_delay = 2

    async def _run_ydlp(self, params: dict) -> Optional[dict]:
        for attempt in range(self.max_retries):
            try:
                if settings.IP_ROTATION_ENABLED:
                    proxy = IPRotator.get_current_proxy()
                    if proxy:
                        params['proxy'] = proxy

                loop = asyncio.get_event_loop()
                with YoutubeDL(params) as ydl:
                    result = await loop.run_in_executor(
                        None,
                        lambda: ydl.extract_info(params['url'], download=False)
                    )
                    return result
            except Exception as e:
                logger.warning(f"yt-dlp attempt {attempt + 1} failed: {str(e)}")
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(self.retry_delay)
        return None

    def _extract_video_id(self, url: str) -> Optional[str]:
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'youtu.be\/([0-9A-Za-z_-]{11})',
            r'music.youtube.com\/watch\?v=([0-9A-Za-z_-]{11})',
            r'youtube.com\/embed\/([0-9A-Za-z_-]{11})',
            r'youtube.com\/live\/([0-9A-Za-z_-]{11})'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def _extract_playlist_id(self, url: str) -> Optional[str]:
        patterns = [
            r'list=([0-9A-Za-z_-]+)',
            r'music.youtube.com\/playlist\?list=([0-9A-Za-z_-]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def get_video_info(self, url: str) -> Optional[Dict]:
        params = {
            **self.ydl_opts,
            'format': 'bestaudio/best',
            'url': url,
        }

        try:
            result = await self._run_ydlp(params)
            if not result:
                return None

            is_live = result.get('is_live', False)
            duration = result.get('duration')
            thumbnails = result.get('thumbnails', [])
            formats = result.get('formats', [])

            thumbnail = thumbnails[-1]['url'] if thumbnails else result.get('thumbnail')

            audio_url = None
            for fmt in formats:
                if fmt.get('acodec') != 'none' and fmt.get('url'):
                    audio_url = fmt['url']
                    break

            return {
                'id': result.get('id'),
                'title': result.get('title', 'Unknown'),
                'url': url,
                'webpage_url': result.get('webpage_url'),
                'duration': duration,
                'formatted_duration': format_duration(duration) if duration else 'Live',
                'is_live': is_live,
                'thumbnail': thumbnail,
                'audio_url': audio_url,
                'uploader': result.get('uploader'),
                'view_count': result.get('view_count'),
                'categories': result.get('categories', []),
                'tags': result.get('tags', []),
                'description': result.get('description'),
                'age_limit': result.get('age_limit', 0)
            }
        except Exception as e:
            logger.error(f"Error getting YouTube video info: {e}")
            return None

    async def search(self, query: str, limit: int = 1) -> Optional[List[Dict]]:
        params = {
            **self.ydl_opts,
            'default_search': 'ytsearch',
            'url': f"ytsearch{limit}:{query}",
        }

        try:
            result = await self._run_ydlp(params)
            if not result or 'entries' not in result:
                return None

            videos = []
            for entry in result['entries']:
                if not entry:
                    continue

                videos.append({
                    'id': entry.get('id'),
                    'title': entry.get('title', 'Unknown'),
                    'url': entry.get('url'),
                    'duration': entry.get('duration'),
                    'formatted_duration': format_duration(entry.get('duration')) if entry.get('duration') else 'Live',
                    'thumbnail': entry.get('thumbnails', [{}])[-1].get('url') if entry.get('thumbnails') else None
                })

            return videos
        except Exception as e:
            logger.error(f"YouTube search error: {e}")
            return None

    async def get_playlist_info(self, url: str) -> Optional[Dict]:
        playlist_id = self._extract_playlist_id(url)
        if not playlist_id:
            return None

        params = {
            **self.ydl_opts,
            'extract_flat': True,
            'url': f"https://www.youtube.com/playlist?list={playlist_id}",
        }

        try:
            result = await self._run_ydlp(params)
            if not result:
                return None

            entries = result.get('entries', [])
            videos = []

            for entry in entries:
                if not entry:
                    continue

                videos.append({
                    'id': entry.get('id'),
                    'title': entry.get('title', 'Unknown'),
                    'url': entry.get('url'),
                    'duration': entry.get('duration'),
                    'formatted_duration': format_duration(entry.get('duration')) if entry.get('duration') else 'Live',
                    'thumbnail': entry.get('thumbnails', [{}])[-1].get('url') if entry.get('thumbnails') else None
                })

            return {
                'id': playlist_id,
                'title': result.get('title'),
                'url': url,
                'thumbnail': result.get('thumbnails', [{}])[-1].get('url') if result.get('thumbnails') else None,
                'uploader': result.get('uploader'),
                'video_count': len(videos),
                'videos': videos
            }
        except Exception as e:
            logger.error(f"Error getting YouTube playlist: {e}")
            return None

    async def get_best_audio_url(self, url: str) -> Optional[str]:
        params = {
            **self.ydl_opts,
            'format': 'bestaudio/best',
            'url': url,
        }

        try:
            result = await self._run_ydlp(params)
            if not result:
                return None

            for fmt in result.get('formats', []):
                if fmt.get('acodec') != 'none' and fmt.get('url'):
                    return fmt['url']
            return None
        except Exception as e:
            logger.error(f"Error getting audio URL: {e}")
            return None

    async def download_audio(self, url: str) -> Optional[Tuple[str, float]]:
        return await Downloader.download_media(url, is_video=False)

    async def download_video(self, url: str) -> Optional[Tuple[str, float]]:
        return await Downloader.download_media(url, is_video=True)

    async def get_live_stream_url(self, url: str) -> Optional[str]:
        params = {
            **self.ydl_opts,
            'format': 'best',
            'url': url,
        }

        try:
            result = await self._run_ydlp(params)
            if not result:
                return None

            for fmt in result.get('formats', []):
                if fmt.get('protocol') in ['m3u8', 'm3u8_native'] and fmt.get('url'):
                    return fmt['url']
            return None
        except Exception as e:
            logger.error(f"Error getting live stream URL: {e}")
            return None

# ✅ Create singleton instance for import use
youtube_service = YouTubeService()
