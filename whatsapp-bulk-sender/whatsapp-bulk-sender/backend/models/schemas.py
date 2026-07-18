"""
Pydantic schemas for request/response validation.
All data contracts between frontend and backend are defined here.
"""

from typing import Any, Optional
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime


class ConnectionStatus(str, Enum):
    """Possible WhatsApp connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    QR_CODE = "qr_code"
    CONNECTED = "connected"
    ERROR = "error"


class SessionResponse(BaseModel):
    """Response when creating or fetching a WhatsApp session."""
    instance_name: str
    status: ConnectionStatus
    qr_code: Optional[str] = None  # Base64 encoded QR image
    phone_number: Optional[str] = None
    profile_name: Optional[str] = None
    message: str = ""


class ColumnMapping(BaseModel):
    """Maps which Excel column contains phone numbers."""
    phone_column: str = Field(..., description="Column name containing phone numbers")
    country_code: str = Field(
        default="1",
        description="Default country code to prepend if missing (without +)"
    )


class ProcessFileResponse(BaseModel):
    """Response after processing an uploaded Excel/CSV file."""
    total_rows: int
    columns: list[str]
    preview: list[dict[str, Any]]  # First 10 rows for preview
    file_id: str  # Temporary ID to reference this file in send request


class MessagePayload(BaseModel):
    """The full payload to initiate a bulk send job."""
    file_id: str = Field(..., description="ID returned from file upload")
    phone_column: str = Field(..., description="Which column has phone numbers")
    country_code: str = Field(default="1", description="Default country code")
    message_template: str = Field(
        ...,
        description="Message with {ColumnName} placeholders",
        min_length=1
    )
    instance_name: str = Field(..., description="WhatsApp instance name")
    media_filename: Optional[str] = Field(None, description="Filename of uploaded media")


class SendStatus(str, Enum):
    """Status of an individual message send attempt."""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class MessageResult(BaseModel):
    """Result for a single message send attempt."""
    row_index: int
    phone: str
    status: SendStatus
    error: Optional[str] = None
    message_id: Optional[str] = None


class JobStatus(BaseModel):
    """Overall status of a bulk send job."""
    job_id: str
    total: int
    sent: int
    failed: int
    skipped: int
    pending: int
    status: str  # "running", "completed", "error"
    results: list[MessageResult] = []
    progress_percent: float = 0.0


# ─────────────────────────────────────────────
# Group Monitor Schemas
# ─────────────────────────────────────────────

class LeadRecord(BaseModel):
    """A detected real estate buyer lead from a group message."""
    lead_id: str
    phone: str
    name: Optional[str] = None
    message: str
    score: int
    lead_tier: str  # "warm" | "hot"
    matched_keywords: list[str] = []
    group_id: str
    group_name: Optional[str] = None
    timestamp: str  # ISO 8601
    instance_name: str


class WebhookMessageData(BaseModel):
    """Inner message data from Evolution API webhook."""
    remoteJid: Optional[str] = None
    fromMe: Optional[bool] = None
    id: Optional[str] = None


class WebhookMessageContent(BaseModel):
    """Message content from Evolution API webhook."""
    conversation: Optional[str] = None
    extendedTextMessage: Optional[dict] = None
    imageMessage: Optional[dict] = None
    videoMessage: Optional[dict] = None


class WebhookPayload(BaseModel):
    """Payload sent by Evolution API for incoming messages."""
    event: Optional[str] = None
    instance: Optional[str] = None
    data: Optional[dict] = None
    sender: Optional[str] = None
    serverUrl: Optional[str] = None
    apikey: Optional[str] = None


class GroupInfo(BaseModel):
    """WhatsApp group metadata."""
    group_id: str
    name: str
    participant_count: int = 0
    description: Optional[str] = None


class GroupMember(BaseModel):
    """A single WhatsApp group participant."""
    phone: str
    name: Optional[str] = None
    is_admin: bool = False


class MonitorSubscription(BaseModel):
    """Request body to subscribe to group monitoring."""
    group_ids: list[str]
    instance_name: str = "bulk-sender-main"
    webhook_url: Optional[str] = None
