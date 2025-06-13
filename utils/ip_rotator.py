import os
import random
import asyncio
import aiohttp
import logging
from typing import Optional, List, Dict
from config.config import settings
from datetime import datetime, timedelta
import backoff
import socket

logger = logging.getLogger(__name__)

class IPRotator:
    def __init__(self):
        self.proxies: List[str] = []
        self.current_proxy: Optional[str] = None
        self.last_rotation: Optional[datetime] = None
        self.proxy_failures: Dict[str, int] = {}
        self.session: Optional[aiohttp.ClientSession] = None
        self.lock = asyncio.Lock()
        self.max_failures = 3
        self.rotation_interval = timedelta(minutes=5)
        self._initialize_proxies()

    def _initialize_proxies(self):
        """Load proxies from file or environment variables"""
        proxy_sources = []

        # 1. Check proxies.txt file
        if os.path.exists(settings.PROXY_FILE):
            with open(settings.PROXY_FILE, 'r') as f:
                proxy_sources.extend(
                    line.strip() for line in f 
                    if line.strip() and not line.startswith('#')
                )

        # 2. Check environment variables
        env_proxies = os.getenv('PROXY_LIST', '')
        if env_proxies:
            proxy_sources.extend(env_proxies.split(','))

        # Validate and store proxies
        self.proxies = [p for p in proxy_sources if self._validate_proxy_format(p)]
        
        if not self.proxies and settings.IP_ROTATION_ENABLED:
            logger.warning("IP rotation enabled but no valid proxies found!")

    @staticmethod
    def _validate_proxy_format(proxy: str) -> bool:
        """Validate proxy URL format"""
        patterns = [
            r'https?://[\w.-]+:\d+',  # HTTP/HTTPS
            r'socks[45]://[\w.-]+:\d+',  # SOCKS
            r'[\w.-]+:\d+',  # Host:Port (no protocol)
        ]
        return any(re.match(pattern, proxy) for pattern in patterns)

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with current proxy"""
        if self.session and not self.session.closed:
            return self.session

        connector = aiohttp.TCPConnector(
            force_close=True,
            enable_cleanup_closed=True,
            ssl=False
        )

        self.session = aiohttp.ClientSession(
            connector=connector,
            trust_env=False,  # Don't use environment proxies
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        return self.session

    async def close_session(self):
        """Close the aiohttp session"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def rotate_proxy(self, force: bool = False) -> Optional[str]:
        """Rotate to a new proxy if needed"""
        if not settings.IP_ROTATION_ENABLED:
            return None

        async with self.lock:
            # Check if rotation is needed
            if not force and self.last_rotation and \
               (datetime.now() - self.last_rotation) < self.rotation_interval:
                return self.current_proxy

            # Filter out bad proxies
            active_proxies = [
                p for p in self.proxies 
                if self.proxy_failures.get(p, 0) < self.max_failures
            ]

            if not active_proxies:
                logger.error("No healthy proxies available!")
                return None

            # Select new proxy
            new_proxy = random.choice(active_proxies)
            
            # Test the new proxy
            if await self._test_proxy(new_proxy):
                self.current_proxy = new_proxy
                self.last_rotation = datetime.now()
                logger.info(f"Rotated to new proxy: {self._mask_proxy(new_proxy)}")
                return new_proxy
            else:
                # Mark failed and retry
                self.proxy_failures[new_proxy] = self.proxy_failures.get(new_proxy, 0) + 1
                logger.warning(f"Proxy failed: {self._mask_proxy(new_proxy)}. Failures: {self.proxy_failures[new_proxy]}")
                return await self.rotate_proxy(force=True)

    @backoff.on_exception(backoff.expo, Exception, max_tries=3)
    async def _test_proxy(self, proxy: str) -> bool:
        """Test if proxy is working"""
        try:
            # Test with a simple HTTP request
            test_url = "http://httpbin.org/ip"
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    test_url,
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        return True
            return False
        except Exception as e:
            logger.debug(f"Proxy test failed for {self._mask_proxy(proxy)}: {str(e)}")
            return False

    def get_current_proxy(self) -> Optional[str]:
        """Get the currently active proxy"""
        return self.current_proxy if settings.IP_ROTATION_ENABLED else None

    def _mask_proxy(self, proxy: str) -> str:
        """Mask sensitive parts of proxy URL for logging"""
        if not proxy:
            return ""
        parsed = urllib.parse.urlparse(proxy)
        if parsed.password:
            return proxy.replace(parsed.password, "*****")
        return proxy

    async def get_public_ip(self) -> Optional[str]:
        """Get the current public IP address"""
        try:
            session = await self.get_session()
            async with session.get(
                "http://httpbin.org/ip",
                proxy=self.current_proxy,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                data = await response.json()
                return data.get('origin')
        except Exception as e:
            logger.error(f"Failed to get public IP: {e}")
            return None

    async def get_proxy_stats(self) -> Dict:
        """Get statistics about proxy usage"""
        return {
            'total_proxies': len(self.proxies),
            'active_proxies': len([p for p in self.proxies if self.proxy_failures.get(p, 0) < self.max_failures]),
            'current_proxy': self._mask_proxy(self.current_proxy),
            'last_rotation': self.last_rotation.isoformat() if self.last_rotation else None,
            'failure_counts': {self._mask_proxy(k): v for k, v in self.proxy_failures.items()}
        }

    async def force_rotation(self) -> bool:
        """Force immediate proxy rotation"""
        return await self.rotate_proxy(force=True)

    async def check_proxy_health(self) -> Dict[str, bool]:
        """Check health of all proxies"""
        results = {}
        for proxy in self.proxies:
            results[proxy] = await self._test_proxy(proxy)
            await asyncio.sleep(0.5)  # Be gentle
        return results

    async def __aenter__(self):
        """Async context manager entry"""
        await self.rotate_proxy()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Async context manager exit"""
        await self.close_session()

# Global instance
ip_rotator = IPRotator()

# Utility functions for easy access
async def get_current_proxy() -> Optional[str]:
    return ip_rotator.get_current_proxy()

async def rotate_proxy(force: bool = False) -> Optional[str]:
    return await ip_rotator.rotate_proxy(force)

async def get_proxy_stats() -> Dict:
    return await ip_rotator.get_proxy_stats()