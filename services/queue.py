import asyncio
from typing import List, Optional, Dict
from datetime import datetime
from database.models import QueueItem
from database.mongodb import mongodb
from config.config import settings
from utils.helpers import format_duration
import logging

logger = logging.getLogger(__name__)

class QueueService:
    @staticmethod
    async def add_to_queue(item: QueueItem) -> bool:
        """Add an item to the queue"""
        try:
            # Get current queue position
            queue_length = await mongodb.queue_collection.count_documents({
                'chat_id': item.chat_id,
                'played': False
            })
            
            item_dict = item.dict(by_alias=True)
            item_dict['position'] = queue_length + 1
            
            await mongodb.queue_collection.insert_one(item_dict)
            logger.info(f"Added item to queue: {item.title} in chat {item.chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding to queue: {e}")
            return False

    @staticmethod
    async def get_queue(chat_id: int) -> List[QueueItem]:
        """Get all unplayed items in the queue"""
        try:
            items = await mongodb.queue_collection.find({
                'chat_id': chat_id,
                'played': False
            }).sort('position', 1).to_list(None)
            
            return [QueueItem(**item) for item in items]
        except Exception as e:
            logger.error(f"Error getting queue: {e}")
            return []

    @staticmethod
    async def get_current_item(chat_id: int) -> Optional[QueueItem]:
        """Get the currently playing item"""
        try:
            item = await mongodb.queue_collection.find_one({
                'chat_id': chat_id,
                'played': True
            }, sort=[('requested_at', -1)])
            
            return QueueItem(**item) if item else None
        except Exception as e:
            logger.error(f"Error getting current item: {e}")
            return None

    @staticmethod
    async def get_next_item(chat_id: int) -> Optional[QueueItem]:
        """Get and mark the next item to be played"""
        try:
            async with await mongodb.client.start_session() as session:
                async with session.start_transaction():
                    # Find the next item
                    item = await mongodb.queue_collection.find_one_and_update(
                        {'chat_id': chat_id, 'played': False},
                        {'$set': {'played': True, 'started_at': datetime.utcnow()}},
                        sort=[('position', 1)],
                        session=session
                    )
                    
                    if item:
                        # Update positions of remaining items
                        await mongodb.queue_collection.update_many(
                            {
                                'chat_id': chat_id,
                                'played': False,
                                'position': {'$gt': item['position']}
                            },
                            {'$inc': {'position': -1}},
                            session=session
                        )
                        
                        return QueueItem(**item)
                    return None
        except Exception as e:
            logger.error(f"Error getting next queue item: {e}")
            return None

    @staticmethod
    async def clear_queue(chat_id: int) -> bool:
        """Clear all items from the queue"""
        try:
            result = await mongodb.queue_collection.delete_many({'chat_id': chat_id})
            logger.info(f"Cleared queue for chat {chat_id}. Removed {result.deleted_count} items")
            return True
        except Exception as e:
            logger.error(f"Error clearing queue: {e}")
            return False

    @staticmethod
    async def remove_queue_item(chat_id: int, position: int) -> bool:
        """Remove a specific item from the queue"""
        try:
            async with await mongodb.client.start_session() as session:
                async with session.start_transaction():
                    # Find and remove the item
                    result = await mongodb.queue_collection.delete_one(
                        {'chat_id': chat_id, 'position': position},
                        session=session
                    )
                    
                    if result.deleted_count == 0:
                        return False
                    
                    # Update positions of remaining items
                    await mongodb.queue_collection.update_many(
                        {
                            'chat_id': chat_id,
                            'position': {'$gt': position}
                        },
                        {'$inc': {'position': -1}},
                        session=session
                    )
                    
                    return True
        except Exception as e:
            logger.error(f"Error removing queue item: {e}")
            return False

    @staticmethod
    async def get_queue_length(chat_id: int) -> int:
        """Get the number of items in the queue"""
        try:
            return await mongodb.queue_collection.count_documents({
                'chat_id': chat_id,
                'played': False
            })
        except Exception as e:
            logger.error(f"Error getting queue length: {e}")
            return 0

    @staticmethod
    async def shuffle_queue(chat_id: int) -> bool:
        """Shuffle the current queue"""
        try:
            async with await mongodb.client.start_session() as session:
                async with session.start_transaction():
                    # Get all unplayed items
                    items = await mongodb.queue_collection.find({
                        'chat_id': chat_id,
                        'played': False
                    }, session=session).to_list(None)
                    
                    if not items:
                        return False
                    
                    # Shuffle positions
                    import random
                    random.shuffle(items)
                    
                    # Update positions
                    for idx, item in enumerate(items, 1):
                        await mongodb.queue_collection.update_one(
                            {'_id': item['_id']},
                            {'$set': {'position': idx}},
                            session=session
                        )
                    
                    return True
        except Exception as e:
            logger.error(f"Error shuffling queue: {e}")
            return False

    @staticmethod
    async def move_item(chat_id: int, from_pos: int, to_pos: int) -> bool:
        """Move an item to a new position in the queue"""
        try:
            async with await mongodb.client.start_session() as session:
                async with session.start_transaction():
                    # Get the item to move
                    item = await mongodb.queue_collection.find_one({
                        'chat_id': chat_id,
                        'position': from_pos
                    }, session=session)
                    
                    if not item:
                        return False
                    
                    # Determine update operation
                    if from_pos < to_pos:
                        # Moving down in queue
                        await mongodb.queue_collection.update_many(
                            {
                                'chat_id': chat_id,
                                'position': {'$gt': from_pos, '$lte': to_pos},
                                'played': False
                            },
                            {'$inc': {'position': -1}},
                            session=session
                        )
                    elif from_pos > to_pos:
                        # Moving up in queue
                        await mongodb.queue_collection.update_many(
                            {
                                'chat_id': chat_id,
                                'position': {'$lt': from_pos, '$gte': to_pos},
                                'played': False
                            },
                            {'$inc': {'position': 1}},
                            session=session
                        )
                    
                    # Update the moved item
                    await mongodb.queue_collection.update_one(
                        {'_id': item['_id']},
                        {'$set': {'position': to_pos}},
                        session=session
                    )
                    
                    return True
        except Exception as e:
            logger.error(f"Error moving queue item: {e}")
            return False

    @staticmethod
    async def get_queue_position(chat_id: int, item_id: str) -> Optional[int]:
        """Get the position of a specific item in the queue"""
        try:
            item = await mongodb.queue_collection.find_one({
                'chat_id': chat_id,
                '_id': item_id
            })
            return item.get('position') if item else None
        except Exception as e:
            logger.error(f"Error getting queue position: {e}")
            return None

    @staticmethod
    async def get_history(chat_id: int, limit: int = 10) -> List[QueueItem]:
        """Get recently played items"""
        try:
            items = await mongodb.queue_collection.find({
                'chat_id': chat_id,
                'played': True
            }).sort('started_at', -1).limit(limit).to_list(None)
            
            return [QueueItem(**item) for item in items]
        except Exception as e:
            logger.error(f"Error getting history: {e}")
            return []

queue_service = QueueService()
