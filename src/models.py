from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class CommitmentType(str, Enum):
    DELIVER = "deliver"
    RESPOND = "respond"
    SCHEDULE = "schedule"
    REVIEW = "review"
    OTHER = "other"

class CommitmentStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    OVERDUE = "overdue"
    UNCERTAIN = "uncertain"
    DISMISSED = "dismissed"

class Direction(str, Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"

class DeadlineType(str, Enum):
    EXPLICIT = "explicit"
    IMPLICIT = "implicit"
    NONE = "none"

class Commitment(BaseModel):
    id: str
    thread_id: str
    message_id: str
    extracted_at: datetime
    email_date: datetime
    
    text: str
    normalized: str
    
    direction: Direction
    commitment_type: CommitmentType
    counterparty_email: str
    counterparty_name: Optional[str] = None
    
    deadline_raw: Optional[str] = None
    deadline_normalized: Optional[datetime] = None
    deadline_type: DeadlineType = DeadlineType.NONE
    
    status: CommitmentStatus = CommitmentStatus.OPEN
    resolved_at: Optional[datetime] = None
    resolved_message_id: Optional[str] = None
    resolution_confidence: Optional[float] = None
    
    extraction_confidence: float
    urgency_score: float = 0.0
    
    notes: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

class SyncState(BaseModel):
    account_email: str
    last_sync_at: datetime
    last_history_id: Optional[str] = None
    total_emails_processed: int = 0
    total_commitments_extracted: int = 0

class ExtractionRun(BaseModel):
    id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    emails_processed: int = 0
    commitments_found: int = 0
    tokens_used: int = 0
    errors: List[str] = Field(default_factory=list)
