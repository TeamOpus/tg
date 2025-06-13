from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
from bson import ObjectId
from utils.helpers import format_duration

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid objectid")
        return ObjectId(v)

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type="string")

class QueueItem(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    chat_id: int
    user_id: int
    item_type: str  # 'youtube', 'spotify', 'local', 'm3u8'
    file_path: Optional[str] = None
    duration: Optional[float] = None
    title: str
    url: Optional[str] = None
    thumbnail: Optional[str] = None
    played: bool = False
    is_live: bool = False
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    position: Optional[int] = None

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
        schema_extra = {
            "example": {
                "chat_id": -100123456789,
                "user_id": 123456789,
                "item_type": "youtube",
                "title": "Example Song",
                "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
                "duration": 213.0,
                "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                "played": False,
                "is_live": False
            }
        }

    @property
    def formatted_duration(self) -> str:
        """Return formatted duration as MM:SS or HH:MM:SS"""
        return format_duration(self.duration) if self.duration else "Live"

class User(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    user_id: int
    username: Optional[str] = None
    first_name: str
    last_name: Optional[str] = None
    is_admin: bool = False
    join_date: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class Chat(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    chat_id: int
    title: str
    type: str  # 'private', 'group', 'supergroup', 'channel'
    is_active: bool = True
    join_date: datetime = Field(default_factory=datetime.utcnow)
    settings: dict = Field(default_factory=dict)  # Custom chat settings

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class PlayerState(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    chat_id: int
    is_playing: bool = False
    is_paused: bool = False
    current_item: Optional[PyObjectId] = None
    volume: int = 100
    loop_mode: str = "none"  # 'none', 'single', 'queue'
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class Playlist(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    owner_id: int
    name: str
    description: Optional[str] = None
    items: List[PyObjectId] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_public: bool = False
    cover_url: Optional[str] = None

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

        