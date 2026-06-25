from __future__ import annotations
from pydantic import BaseModel, ConfigDict
from datetime import datetime
import uuid

class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class IdOut(ORMBase):
    id: uuid.UUID

class Message(ORMBase):
    message: str
