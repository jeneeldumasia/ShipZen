from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_serializer
from enum import Enum

class ProjectStatus(str, Enum):
    PROVISIONING = "Provisioning"
    READY = "Ready"
    TERMINATING = "Terminating"
    FAILED = "Failed"

class ProjectSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str = Field(alias="_id")
    name: str
    namespace: str
    status: ProjectStatus = Field(default=ProjectStatus.PROVISIONING)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None

    @field_serializer('created_at', 'deleted_at')
    def serialize_dt(self, dt: datetime, _info):
        return dt.isoformat() if dt else None
