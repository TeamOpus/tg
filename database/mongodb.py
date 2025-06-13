import logging
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import PyMongoError
from config.config import settings
from database.models import QueueItem, User, Chat, PlayerState, Playlist
from utils.helpers import format_duration
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)

class MongoDB:
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
        self._connect_lock = asyncio.Lock()

    async def connect(self):
        """Establish database connection with retry logic"""
        async with self._connect_lock:
            if self.client and self.db:
                return

            max_retries = 3
            retry_delay = 2

            for attempt in range(max_retries):
                try:
                    self.client = AsyncIOMotorClient(
                        settings.DATABASE_URL,
                        maxPoolSize=100,
                        minPoolSize=10,
                        connectTimeoutMS=5000,
                        serverSelectionTimeoutMS=5000
                    )
                    self.db = self.client[settings.DATABASE_NAME]

                    # Test the connection
                    await self.client.admin.command('ping')
                    logger.info("Successfully connected to MongoDB")
                    await self._ensure_indexes()
                    return
                except PyMongoError as e:
                    logger.error(
                        f"Connection attempt {attempt + 1} failed: {str(e)}"
                    )
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(retry_delay * (attempt + 1))

    async def _ensure_indexes(self):
        """Create necessary indexes for optimal performance"""
        try:
            # Queue items indexes
            await self.db.queue_items.create_index([
                ("chat_id", 1),
                ("played", 1),
                ("position", 1)
            ])
            await self.db.queue_items.create_index([
                ("chat_id", 1),
                ("user_id", 1)
            ])

            # Users indexes
            await self.db.users.create_index("user_id", unique=True)
            await self.db.users.create_index("username")

            # Player state indexes
            await self.db.player_states.create_index("chat_id", unique=True)

            logger.debug("Database indexes verified/created")
        except PyMongoError as e:
            logger.error(f"Error creating indexes: {str(e)}")

    async def close(self):
        """Close the database connection"""
        if self.client:
            self.client.close()
            self.client = None
            self.db = None
            logger.info("MongoDB connection closed")

    # ======================
    # Queue Item Operations
    # ======================

    async def add_to_queue(self, item: QueueItem) -> bool:
        """Add an item to the queue"""
        try:
            # Get current queue position
            queue_length = await self.db.queue_items.count_documents({
                "chat_id": item.chat_id,
                "played": False
            })
            
            item_dict = item.dict(by_alias=True)
            item_dict["position"] = queue_length + 1
            item_dict["added_at"] = datetime.utcnow()
            
            await self.db.queue_items.insert_one(item_dict)
            logger.debug(f"Added item to queue: {item.title}")
            return True
        except PyMongoError as e:
            logger.error(f"Error adding to queue: {str(e)}")
            return False

    async def get_queue(self, chat_id: int) -> List[QueueItem]:
        """Get all unplayed items in the queue"""
        try:
            items = await self.db.queue_items.find({
                "chat_id": chat_id,
                "played": False
            }).sort("position", 1).to_list(None)
            
            return [QueueItem(**item) for item in items]
        except PyMongoError as e:
            logger.error(f"Error getting queue: {str(e)}")
            return []

    async def get_next_queue_item(self, chat_id: int) -> Optional[QueueItem]:
        """Get and mark the next item to be played"""
        async with await self.client.start_session() as session:
            try:
                async with session.start_transaction():
                    # Find and update the next item
                    item = await self.db.queue_items.find_one_and_update(
                        {"chat_id": chat_id, "played": False},
                        {"$set": {"played": True, "started_at": datetime.utcnow()}},
                        sort=[("position", 1)],
                        session=session
                    )
                    
                    if item:
                        # Update positions of remaining items
                        await self.db.queue_items.update_many(
                            {
                                "chat_id": chat_id,
                                "played": False,
                                "position": {"$gt": item["position"]}
                            },
                            {"$inc": {"position": -1}},
                            session=session
                        )
                        return QueueItem(**item)
                    return None
            except PyMongoError as e:
                logger.error(f"Error getting next queue item: {str(e)}")
                await session.abort_transaction()
                return None

    async def clear_queue(self, chat_id: int) -> bool:
        """Clear all items from the queue"""
        try:
            result = await self.db.queue_items.delete_many({"chat_id": chat_id})
            logger.info(f"Cleared queue for chat {chat_id}")
            return result.deleted_count > 0
        except PyMongoError as e:
            logger.error(f"Error clearing queue: {str(e)}")
            return False

    async def remove_queue_item(self, chat_id: int, position: int) -> bool:
        """Remove a specific item from the queue"""
        async with await self.client.start_session() as session:
            try:
                async with session.start_transaction():
                    # Find and remove the item
                    result = await self.db.queue_items.delete_one(
                        {"chat_id": chat_id, "position": position},
                        session=session
                    )
                    
                    if result.deleted_count == 0:
                        return False
                    
                    # Update positions of remaining items
                    await self.db.queue_items.update_many(
                        {"chat_id": chat_id, "position": {"$gt": position}},
                        {"$inc": {"position": -1}},
                        session=session
                    )
                    return True
            except PyMongoError as e:
                logger.error(f"Error removing queue item: {str(e)}")
                await session.abort_transaction()
                return False

    # ======================
    # User Operations
    # ======================

    async def get_or_create_user(self, user_id: int, **kwargs) -> User:
        """Get or create a user in the database"""
        try:
            user = await self.db.users.find_one({"user_id": user_id})
            if user:
                return User(**user)
            
            # Create new user
            new_user = User(
                user_id=user_id,
                **kwargs
            )
            await self.db.users.insert_one(new_user.dict(by_alias=True))
            return new_user
        except PyMongoError as e:
            logger.error(f"Error getting/creating user: {str(e)}")
            raise

    async def update_user(self, user_id: int, **kwargs) -> bool:
        """Update user information"""
        try:
            result = await self.db.users.update_one(
                {"user_id": user_id},
                {"$set": kwargs},
                upsert=False
            )
            return result.modified_count > 0
        except PyMongoError as e:
            logger.error(f"Error updating user: {str(e)}")
            return False

    async def is_user_banned(self, user_id: int) -> bool:
        """Check if user is banned"""
        try:
            user = await self.db.users.find_one(
                {"user_id": user_id, "is_banned": True}
            )
            return user is not None
        except PyMongoError as e:
            logger.error(f"Error checking ban status: {str(e)}")
            return False

    # ======================
    # Player State Operations
    # ======================

    async def get_player_state(self, chat_id: int) -> Optional[PlayerState]:
        """Get current player state for a chat"""
        try:
            state = await self.db.player_states.find_one({"chat_id": chat_id})
            return PlayerState(**state) if state else None
        except PyMongoError as e:
            logger.error(f"Error getting player state: {str(e)}")
            return None

    async def update_player_state(self, state: PlayerState) -> bool:
        """Update or create player state"""
        try:
            await self.db.player_states.update_one(
                {"chat_id": state.chat_id},
                {"$set": state.dict(by_alias=True)},
                upsert=True
            )
            return True
        except PyMongoError as e:
            logger.error(f"Error updating player state: {str(e)}")
            return False

    # ======================
    # Playlist Operations
    # ======================

    async def create_playlist(self, playlist: Playlist) -> bool:
        """Create a new playlist"""
        try:
            await self.db.playlists.insert_one(playlist.dict(by_alias=True))
            return True
        except PyMongoError as e:
            logger.error(f"Error creating playlist: {str(e)}")
            return False

    async def get_user_playlists(self, owner_id: int) -> List[Playlist]:
        """Get all playlists for a user"""
        try:
            playlists = await self.db.playlists.find(
                {"owner_id": owner_id}
            ).to_list(None)
            return [Playlist(**p) for p in playlists]
        except PyMongoError as e:
            logger.error(f"Error getting user playlists: {str(e)}")
            return []

    async def add_to_playlist(self, playlist_id: str, item: QueueItem) -> bool:
        """Add an item to a playlist"""
        try:
            result = await self.db.playlists.update_one(
                {"_id": playlist_id},
                {"$push": {"items": item.dict(by_alias=True)}}
            )
            return result.modified_count > 0
        except PyMongoError as e:
            logger.error(f"Error adding to playlist: {str(e)}")
            return False

    # ======================
    # Maintenance Operations
    # ======================

    async def cleanup_old_items(self, days: int = 30) -> int:
        """Cleanup items older than specified days"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            result = await self.db.queue_items.delete_many({
                "played": True,
                "started_at": {"$lt": cutoff_date}
            })
            logger.info(f"Cleaned up {result.deleted_count} old queue items")
            return result.deleted_count
        except PyMongoError as e:
            logger.error(f"Error cleaning up old items: {str(e)}")
            return 0

    async def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        try:
            return {
                "queue_items": await self.db.queue_items.count_documents({}),
                "users": await self.db.users.count_documents({}),
                "player_states": await self.db.player_states.count_documents({}),
                "playlists": await self.db.playlists.count_documents({}),
            }
        except PyMongoError as e:
            logger.error(f"Error getting database stats: {str(e)}")
            return {}

# Global MongoDB instance
mongodb = MongoDB()

