import re
import logging
from typing import Optional, List, Dict
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.exceptions import SpotifyException
from config.config import settings
from utils.helpers import format_duration
from utils.ip_rotator import IPRotator
import asyncio

logger = logging.getLogger(__name__)

class SpotifyService:
    def __init__(self):
        self.auth_manager = SpotifyClientCredentials(
            client_id=settings.SPOTIFY_CLIENT_ID,
            client_secret=settings.SPOTIFY_CLIENT_SECRET
        )
        self.sp = Spotify(auth_manager=self.auth_manager)
        self.max_retries = 3
        self.retry_delay = 2

    async def _make_request(self, func, *args, **kwargs):
        """Wrapper for Spotify requests with retry logic"""
        for attempt in range(self.max_retries):
            try:
                if settings.IP_ROTATION_ENABLED:
                    IPRotator.rotate_proxy()
                
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, func, *args, **kwargs)
                return result
            except SpotifyException as e:
                if e.http_status == 429 or 500 <= e.http_status < 600:
                    wait_time = int(e.headers.get('Retry-After', self.retry_delay))
                    logger.warning(f"Spotify API error (attempt {attempt + 1}): {e}. Retrying in {wait_time}s")
                    await asyncio.sleep(wait_time)
                else:
                    raise
            except Exception as e:
                logger.error(f"Spotify request failed: {e}")
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(self.retry_delay)
        return None

    @staticmethod
    def _extract_spotify_id(url: str) -> Optional[str]:
        """Extract track/playlist ID from Spotify URL"""
        patterns = [
            r'spotify:track:([a-zA-Z0-9]+)',
            r'spotify.com/track/([a-zA-Z0-9]+)',
            r'spotify:playlist:([a-zA-Z0-9]+)',
            r'spotify.com/playlist/([a-zA-Z0-9]+)',
            r'spotify:album:([a-zA-Z0-9]+)',
            r'spotify.com/album/([a-zA-Z0-9]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def get_track(self, url: str) -> Optional[Dict]:
        """Get track metadata from Spotify URL"""
        track_id = self._extract_spotify_id(url)
        if not track_id:
            return None

        try:
            track = await self._make_request(self.sp.track, track_id)
            if not track:
                return None

            return {
                'id': track['id'],
                'name': track['name'],
                'artists': [artist['name'] for artist in track['artists']],
                'duration_ms': track['duration_ms'],
                'url': track['external_urls']['spotify'],
                'preview_url': track.get('preview_url'),
                'cover_url': track['album']['images'][0]['url'] if track['album']['images'] else None,
                'formatted_duration': format_duration(track['duration_ms'] / 1000),
                'artist_string': ', '.join(artist['name'] for artist in track['artists'])
            }
        except Exception as e:
            logger.error(f"Error getting Spotify track: {e}")
            return None

    async def get_playlist(self, url: str) -> Optional[List[Dict]]:
        """Get all tracks from a Spotify playlist"""
        playlist_id = self._extract_spotify_id(url)
        if not playlist_id:
            return None

        try:
            playlist = await self._make_request(self.sp.playlist, playlist_id)
            if not playlist:
                return None

            results = await self._make_request(self.sp.playlist_items, playlist_id)
            tracks = []
            
            while results:
                for item in results['items']:
                    track = item.get('track')
                    if track and track.get('id'):  # Skip None tracks and local tracks
                        tracks.append({
                            'id': track['id'],
                            'name': track['name'],
                            'artists': [artist['name'] for artist in track['artists']],
                            'duration_ms': track['duration_ms'],
                            'url': track['external_urls']['spotify'],
                            'artist_string': ', '.join(artist['name'] for artist in track['artists'])
                        })
                
                if results['next']:
                    results = await self._make_request(self.sp.next, results)
                else:
                    break

            return {
                'name': playlist['name'],
                'owner': playlist['owner']['display_name'],
                'total_tracks': playlist['tracks']['total'],
                'cover_url': playlist['images'][0]['url'] if playlist['images'] else None,
                'tracks': tracks
            }
        except Exception as e:
            logger.error(f"Error getting Spotify playlist: {e}")
            return None

    async def get_album(self, url: str) -> Optional[List[Dict]]:
        """Get all tracks from a Spotify album"""
        album_id = self._extract_spotify_id(url)
        if not album_id:
            return None

        try:
            album = await self._make_request(self.sp.album, album_id)
            if not album:
                return None

            results = await self._make_request(self.sp.album_tracks, album_id)
            tracks = []
            
            while results:
                for track in results['items']:
                    tracks.append({
                        'id': track['id'],
                        'name': track['name'],
                        'artists': [artist['name'] for artist in track['artists']],
                        'duration_ms': track['duration_ms'],
                        'url': track['external_urls']['spotify'],
                        'artist_string': ', '.join(artist['name'] for artist in track['artists'])
                    })
                
                if results['next']:
                    results = await self._make_request(self.sp.next, results)
                else:
                    break

            return {
                'name': album['name'],
                'artists': [artist['name'] for artist in album['artists']],
                'total_tracks': album['total_tracks'],
                'cover_url': album['images'][0]['url'] if album['images'] else None,
                'tracks': tracks
            }
        except Exception as e:
            logger.error(f"Error getting Spotify album: {e}")
            return None

    async def search(self, query: str, limit: int = 1) -> Optional[List[Dict]]:
        """Search for tracks on Spotify"""
        try:
            results = await self._make_request(self.sp.search, q=query, limit=limit, type='track')
            if not results:
                return None

            tracks = []
            for track in results['tracks']['items']:
                tracks.append({
                    'id': track['id'],
                    'name': track['name'],
                    'artists': [artist['name'] for artist in track['artists']],
                    'duration_ms': track['duration_ms'],
                    'url': track['external_urls']['spotify'],
                    'artist_string': ', '.join(artist['name'] for artist in track['artists'])
                })
            
            return tracks
        except Exception as e:
            logger.error(f"Spotify search error: {e}")
            return None

spotify_service = SpotifyService()
