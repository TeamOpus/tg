import os
import asyncio
import logging
from typing import Optional, Tuple, List
from yt_dlp import YoutubeDL
from config.config import settings
from utils.ip_rotator import IPRotator
from utils.helpers import format_duration
import re
import subprocess
import shutil

logger = logging.getLogger(__name__)

class Downloader:
    def __init__(self):
        self.downloads_dir = "downloads"
        self.temp_dir = "temp"
        self.max_concurrent = settings.MAX_CONCURRENT_DOWNLOADS
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        self._ensure_dirs()
        self.active_downloads = {}

    def _ensure_dirs(self):
        """Ensure download directories exist"""
        os.makedirs(self.downloads_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

    async def download_media(
        self,
        url: str,
        is_video: bool = False,
        quality: str = "best",
        retries: int = 3
    ) -> Optional[Tuple[str, float]]:
        """Download media from URL with retry logic"""
        async with self.semaphore:
            for attempt in range(1, retries + 1):
                try:
                    if is_video:
                        return await self._download_video(url, quality)
                    else:
                        return await self._download_audio(url, quality)
                except Exception as e:
                    logger.error(f"Download attempt {attempt} failed for {url}: {e}")
                    if attempt == retries:
                        logger.error(f"All download attempts failed for {url}")
                        return None
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff

    async def _download_audio(self, url: str, quality: str) -> Optional[Tuple[str, float]]:
        """Download audio stream from URL"""
        ydl_opts = {
            'format': f'{quality}audio/{quality}',
            'outtmpl': os.path.join(self.downloads_dir, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'force_ipv4': True,
            'socket_timeout': settings.DOWNLOAD_TIMEOUT,
            'noplaylist': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'extractaudio': True,
            'audioformat': 'mp3',
        }

        if settings.IP_ROTATION_ENABLED:
            proxy = IPRotator.get_current_proxy()
            if proxy:
                ydl_opts['proxy'] = proxy

        try:
            with YoutubeDL(ydl_opts) as ydl:
                loop = asyncio.get_event_loop()
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
                
                if not info:
                    raise Exception("Failed to extract info")
                
                filename = ydl.prepare_filename(info)
                base, _ = os.path.splitext(filename)
                audio_file = f"{base}.mp3"
                
                if not os.path.exists(audio_file):
                    raise Exception("Audio file not created")
                
                duration = info.get('duration', 0)
                return audio_file, duration
        except Exception as e:
            logger.error(f"Audio download failed: {e}")
            raise

    async def _download_video(self, url: str, quality: str) -> Optional[Tuple[str, float]]:
        """Download video stream from URL"""
        ydl_opts = {
            'format': f'{quality}video+{quality}audio/{quality}',
            'outtmpl': os.path.join(self.downloads_dir, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'force_ipv4': True,
            'socket_timeout': settings.DOWNLOAD_TIMEOUT,
            'noplaylist': True,
        }

        if settings.IP_ROTATION_ENABLED:
            proxy = IPRotator.get_current_proxy()
            if proxy:
                ydl_opts['proxy'] = proxy

        try:
            with YoutubeDL(ydl_opts) as ydl:
                loop = asyncio.get_event_loop()
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
                
                if not info:
                    raise Exception("Failed to extract info")
                
                video_file = ydl.prepare_filename(info)
                
                if not os.path.exists(video_file):
                    raise Exception("Video file not created")
                
                duration = info.get('duration', 0)
                return video_file, duration
        except Exception as e:
            logger.error(f"Video download failed: {e}")
            raise

    async def get_direct_stream_url(self, url: str, is_video: bool = False) -> Optional[str]:
        """Get direct stream URL without downloading"""
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best' if is_video else 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'force_ipv4': True,
            'socket_timeout': 30,
            'extract_flat': True,
        }

        if settings.IP_ROTATION_ENABLED:
            proxy = IPRotator.get_current_proxy()
            if proxy:
                ydl_opts['proxy'] = proxy

        try:
            with YoutubeDL(ydl_opts) as ydl:
                loop = asyncio.get_event_loop()
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                
                if not info:
                    return None
                
                if 'url' in info:
                    return info['url']
                
                if 'entries' in info:
                    for entry in info['entries']:
                        if entry and 'url' in entry:
                            return entry['url']
                
                return None
        except Exception as e:
            logger.error(f"Failed to get stream URL: {e}")
            return None

    async def get_media_info(self, url: str) -> Optional[dict]:
        """Get media information without downloading"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'force_ipv4': True,
            'socket_timeout': 30,
            'extract_flat': False,
        }

        if settings.IP_ROTATION_ENABLED:
            proxy = IPRotator.get_current_proxy()
            if proxy:
                ydl_opts['proxy'] = proxy

        try:
            with YoutubeDL(ydl_opts) as ydl:
                loop = asyncio.get_event_loop()
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                
                if not info:
                    return None
                
                return {
                    'id': info.get('id'),
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'formatted_duration': format_duration(info.get('duration', 0)),
                    'thumbnail': info.get('thumbnail'),
                    'uploader': info.get('uploader'),
                    'is_live': info.get('is_live', False),
                    'url': info.get('webpage_url', url),
                    'extractor': info.get('extractor'),
                    'view_count': info.get('view_count'),
                    'categories': info.get('categories', []),
                    'tags': info.get('tags', []),
                }
        except Exception as e:
            logger.error(f"Failed to get media info: {e}")
            return None

    async def cleanup_downloads(self, older_than: int = 3600) -> int:
        """Clean up old download files"""
        count = 0
        try:
            now = time.time()
            for filename in os.listdir(self.downloads_dir):
                filepath = os.path.join(self.downloads_dir, filename)
                if os.path.isfile(filepath):
                    file_age = now - os.path.getmtime(filepath)
                    if file_age > older_than:
                        try:
                            os.remove(filepath)
                            count += 1
                        except Exception as e:
                            logger.error(f"Error deleting {filepath}: {e}")
            logger.info(f"Cleaned up {count} old files")
            return count
        except Exception as e:
            logger.error(f"Error during downloads cleanup: {e}")
            return count

    async def convert_to_mp3(self, input_path: str) -> Optional[str]:
        """Convert any audio file to MP3 format"""
        if not os.path.exists(input_path):
            return None

        output_path = os.path.splitext(input_path)[0] + '.mp3'
        
        try:
            cmd = [
                'ffmpeg',
                '-i', input_path,
                '-codec:a', 'libmp3lame',
                '-qscale:a', '2',
                '-y',  # Overwrite without asking
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                raise Exception(f"FFmpeg error: {stderr.decode()}")
            
            if os.path.exists(output_path):
                return output_path
            return None
        except Exception as e:
            logger.error(f"Audio conversion failed: {e}")
            return None

    async def get_file_duration(self, file_path: str) -> Optional[float]:
        """Get duration of a media file in seconds"""
        if not os.path.exists(file_path):
            return None

        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                file_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return float(stdout.decode().strip())
            return None
        except Exception as e:
            logger.error(f"Failed to get file duration: {e}")
            return None

downloader = Downloader()
