from datetime import datetime
from typing import List, Optional, Union, Dict, Any
from pydantic import BaseModel, EmailStr, Field, HttpUrl

from app.db.models import LeadStatus, ConversationChannel, LeadTemperature, ObjectionType


class LeadBase(BaseModel):
    """Base Lead model for common attributes."""
    first_name: str
    last_name: str
    email: EmailStr
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    source: Optional[str] = None
    preferred_channel: ConversationChannel = ConversationChannel.EMAIL


class LeadCreate(LeadBase):
    """Model for creating a new lead."""
    notes: Optional[str] = None


class LeadUpdate(BaseModel):
    """Model for updating lead information."""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    source: Optional[str] = None
    status: Optional[LeadStatus] = None
    notes: Optional[str] = None
    budget: Optional[str] = None
    needs: Optional[str] = None
    objections: Optional[str] = None
    preferred_channel: Optional[ConversationChannel] = None
    is_active: Optional[bool] = None
    lead_score: Optional[float] = None
    temperature: Optional[LeadTemperature] = None
    engagement_level: Optional[int] = None


class ConversationBase(BaseModel):
    """Base Conversation model for common attributes."""
    lead_id: int
    channel: ConversationChannel
    is_from_lead: bool
    content: str


class ConversationCreate(ConversationBase):
    """Model for creating a new conversation message."""
    pass


class ConversationResponse(ConversationBase):
    """Model for conversation response from API."""
    id: int
    created_at: datetime
    sentiment_score: Optional[float] = None
    contains_buying_signal: bool = False
    contains_objection: bool = False
    question_answered: bool = False

    class Config:
        orm_mode = True


class DetectedObjectionResponse(BaseModel):
    """Model for objection detection response."""
    id: int
    objection_type: ObjectionType
    objection_text: str
    response_text: Optional[str] = None
    handled_successfully: Optional[bool] = None
    created_at: datetime

    class Config:
        orm_mode = True


class LeadResponse(LeadBase):
    """Model for lead response from API."""
    id: int
    status: LeadStatus
    notes: Optional[str] = None
    budget: Optional[str] = None
    needs: Optional[str] = None
    objections: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_contact: Optional[datetime] = None
    followup_count: int
    is_active: bool
    lead_score: float
    temperature: LeadTemperature
    engagement_level: int
    buying_signals: int
    question_responses: int
    conversations: List[ConversationResponse] = []
    detected_objections: List[DetectedObjectionResponse] = []

    class Config:
        orm_mode = True


class IncomingMessage(BaseModel):
    """Model for incoming messages from leads."""
    lead_email: EmailStr = Field(..., description="Email of the lead sending the message")
    content: str = Field(..., description="Content of the message")
    channel: ConversationChannel = Field(ConversationChannel.EMAIL, description="Channel through which the message was received")


class AgentResponse(BaseModel):
    """Model for agent responses to incoming messages."""
    content: str = Field(..., description="Content of the agent's response")
    scheduled_actions: List[str] = Field(default_factory=list, description="Any actions scheduled as a result of this message")
    detected_objections: List[str] = Field(default_factory=list, description="Any objections detected in the message")
    lead_score_change: Optional[float] = Field(None, description="Change in lead score as a result of this message")


class ScheduledActionCreate(BaseModel):
    """Model for creating a scheduled action."""
    lead_id: int
    action_type: str
    channel: ConversationChannel
    content: Optional[str] = None
    scheduled_for: datetime
    priority: int = 1


class ScheduledActionResponse(ScheduledActionCreate):
    """Model for scheduled action response from API."""
    id: int
    is_executed: bool
    executed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        orm_mode = True


class ConversationSummaryCreate(BaseModel):
    """Model for creating a conversation summary."""
    lead_id: int
    start_time: datetime
    end_time: datetime
    channel: ConversationChannel
    summary_text: str
    key_points: Optional[str] = None
    detected_needs: Optional[str] = None
    detected_objections: Optional[str] = None
    next_steps: Optional[str] = None


class ConversationSummaryResponse(ConversationSummaryCreate):
    """Model for conversation summary response from API."""
    id: int
    created_at: datetime

    class Config:
        orm_mode = True


class ObjectionLibraryCreate(BaseModel):
    """Model for creating an objection library entry."""
    objection_type: ObjectionType
    name: str
    description: str
    example_phrases: str
    response_templates: str


class ObjectionLibraryResponse(ObjectionLibraryCreate):
    """Model for objection library response from API."""
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class BusinessConfigItem(BaseModel):
    """Model for a single item in a business configuration."""
    id: str
    name: str
    description: str
    details: Dict[str, Any] = {}


class BusinessConfigCreate(BaseModel):
    """Model for creating a business configuration."""
    name: str
    products: Optional[List[BusinessConfigItem]] = None
    pricing: Optional[List[BusinessConfigItem]] = None
    faqs: Optional[List[Dict[str, str]]] = None
    testimonials: Optional[List[Dict[str, str]]] = None
    company_info: Optional[Dict[str, Any]] = None
    value_props: Optional[List[str]] = None


class BusinessConfigResponse(BusinessConfigCreate):
    """Model for business configuration response from API."""
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class NotificationCreate(BaseModel):
    """Model for creating a notification."""
    lead_id: int
    notification_type: str
    content: str


class NotificationResponse(NotificationCreate):
    """Model for notification response from API."""
    id: int
    is_read: bool
    is_handled: bool
    created_at: datetime
    read_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class LeadScoreUpdate(BaseModel):
    """Model for updating a lead's score."""
    lead_id: int
    score_change: float
    reason: str


class DashboardSummary(BaseModel):
    """Model for dashboard summary data."""
    total_leads: int
    active_conversations: int
    hot_leads: int
    warm_leads: int
    cold_leads: int
    leads_requiring_followup: int
    total_scheduled_actions: int
    unread_notifications: int


class ProductRecommendationResponse(BaseModel):
    """Model for product recommendation response from API."""
    recommendation_id: int
    product_id: int
    product_name: str
    product_description: str
    price: float
    confidence_score: float
    reasons: List[str]
    recommended_at: str
    was_accepted: Optional[bool] = None

    class Config:
        orm_mode = True 