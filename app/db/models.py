from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Enum as SQLAEnum, Float, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class LeadStatus(str, Enum):
    NEW = "new"
    QUALIFYING = "qualifying"
    INTERESTED = "interested"
    QUALIFIED = "qualified"
    NEGOTIATING = "negotiating"
    MEETING_SCHEDULED = "meeting_scheduled"
    WON = "won"
    LOST = "lost"
    DORMANT = "dormant"


class ConversationChannel(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    CHAT = "chat"
    WHATSAPP = "whatsapp"
    FACEBOOK = "facebook"
    WEBCHAT = "webchat"


class LeadTemperature(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class ObjectionType(str, Enum):
    PRICE = "price"
    TIMING = "timing"
    TRUST = "trust"
    COMPETITION = "competition"
    VALUE = "value"
    NEED = "need"
    AUTHORITY = "authority"
    OTHER = "other"


class Lead(Base):
    """Model for storing lead information."""
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    email = Column(String(255), index=True, unique=True)
    phone = Column(String(20), nullable=True)
    company = Column(String(255), nullable=True)
    job_title = Column(String(255), nullable=True)
    source = Column(String(100), nullable=True)  # Where the lead came from
    status = Column(SQLAEnum(LeadStatus), default=LeadStatus.NEW)
    notes = Column(Text, nullable=True)
    budget = Column(String(100), nullable=True)
    needs = Column(Text, nullable=True)
    objections = Column(Text, nullable=True)
    preferred_channel = Column(SQLAEnum(ConversationChannel), default=ConversationChannel.EMAIL)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_contact = Column(DateTime, nullable=True)
    followup_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    
    # New fields for lead scoring and classification
    lead_score = Column(Float, default=0.0)
    temperature = Column(SQLAEnum(LeadTemperature), default=LeadTemperature.COLD)
    engagement_level = Column(Integer, default=0)  # 0-10 scale
    buying_signals = Column(Integer, default=0)
    question_responses = Column(Integer, default=0)  # Number of qualifying questions answered
    last_interaction_length = Column(Integer, default=0)  # Character length of last message
    
    # Relationships
    conversations = relationship("Conversation", back_populates="lead", cascade="all, delete-orphan")
    summaries = relationship("ConversationSummary", back_populates="lead", cascade="all, delete-orphan")
    detected_objections = relationship("DetectedObjection", back_populates="lead", cascade="all, delete-orphan")
    product_recommendations = relationship("ProductRecommendation", back_populates="lead", cascade="all, delete-orphan")
    preferences = relationship("UserPreference", back_populates="lead", cascade="all, delete-orphan")
    
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()
    
    def __repr__(self) -> str:
        return f"<Lead {self.full_name} ({self.email})>"


class Conversation(Base):
    """Model for storing conversation history with leads."""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    channel = Column(SQLAEnum(ConversationChannel))
    is_from_lead = Column(Boolean, default=False)  # True if message is from lead, False if from agent
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # New fields for tracking conversation metrics
    sentiment_score = Column(Float, nullable=True)  # -1 to 1 scale
    contains_buying_signal = Column(Boolean, default=False)
    contains_objection = Column(Boolean, default=False)
    question_answered = Column(Boolean, default=False)
    
    # Relationships
    lead = relationship("Lead", back_populates="conversations")
    
    def __repr__(self) -> str:
        direction = "Lead → Agent" if self.is_from_lead else "Agent → Lead"
        return f"<Message {direction} at {self.created_at.strftime('%Y-%m-%d %H:%M')}>"


class ScheduledAction(Base):
    """Model for storing scheduled actions like follow-ups."""
    __tablename__ = "scheduled_actions"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    action_type = Column(String(50))  # e.g., "followup", "reminder", etc.
    channel = Column(SQLAEnum(ConversationChannel))
    content = Column(Text, nullable=True)
    scheduled_for = Column(DateTime)
    is_executed = Column(Boolean, default=False)
    executed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    priority = Column(Integer, default=1)  # 1 = low, 2 = medium, 3 = high
    
    # Relationships
    lead = relationship("Lead")
    
    def __repr__(self) -> str:
        status = "Executed" if self.is_executed else "Pending"
        return f"<ScheduledAction {self.action_type} for {self.lead.email} - {status}>"


class ObjectionLibrary(Base):
    """Model for storing objection templates and responses."""
    __tablename__ = "objection_library"
    
    id = Column(Integer, primary_key=True, index=True)
    objection_type = Column(SQLAEnum(ObjectionType))
    name = Column(String(255))
    description = Column(Text)
    example_phrases = Column(Text)  # Stored as comma-separated phrases
    response_templates = Column(Text)  # Stored as JSON string of response templates
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self) -> str:
        return f"<ObjectionLibrary {self.objection_type} - {self.name}>"


class DetectedObjection(Base):
    """Model for tracking objections detected in conversations."""
    __tablename__ = "detected_objections"
    
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    objection_type = Column(SQLAEnum(ObjectionType))
    objection_text = Column(Text)
    response_text = Column(Text, nullable=True)
    handled_successfully = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    lead = relationship("Lead", back_populates="detected_objections")
    
    def __repr__(self) -> str:
        return f"<DetectedObjection {self.objection_type} for {self.lead.email}>"


class ConversationSummary(Base):
    """Model for storing summaries of conversations."""
    __tablename__ = "conversation_summaries"
    
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    channel = Column(SQLAEnum(ConversationChannel))
    summary_text = Column(Text)
    key_points = Column(Text, nullable=True)
    detected_needs = Column(Text, nullable=True)
    detected_objections = Column(Text, nullable=True)
    next_steps = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    lead = relationship("Lead", back_populates="summaries")
    
    def __repr__(self) -> str:
        return f"<ConversationSummary for {self.lead.email} at {self.end_time.strftime('%Y-%m-%d %H:%M')}>"


class BusinessConfiguration(Base):
    """Model for storing customizable business-specific information."""
    __tablename__ = "business_configurations"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True)
    is_active = Column(Boolean, default=True)
    products = Column(JSON, nullable=True)  # JSON structure with product info
    pricing = Column(JSON, nullable=True)  # JSON structure with pricing info
    faqs = Column(JSON, nullable=True)  # JSON structure with FAQ info
    testimonials = Column(JSON, nullable=True)  # JSON structure with testimonial info
    company_info = Column(JSON, nullable=True)  # JSON structure with company info
    value_props = Column(JSON, nullable=True)  # JSON structure with value propositions
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self) -> str:
        return f"<BusinessConfiguration {self.name}>"


class Notification(Base):
    """Model for storing notifications for human escalation."""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    notification_type = Column(String(50))  # e.g., "escalation", "high_score", "new_lead"
    content = Column(Text)
    is_read = Column(Boolean, default=False)
    is_handled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    read_at = Column(DateTime, nullable=True)
    
    # Relationships
    lead = relationship("Lead")
    
    def __repr__(self) -> str:
        status = "Read" if self.is_read else "Unread"
        return f"<Notification {self.notification_type} for {self.lead.email} - {status}>"


class ProductCategory(Base):
    """Model for product categories."""
    __tablename__ = "product_categories"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True)
    description = Column(Text, nullable=True)
    parent_id = Column(Integer, ForeignKey("product_categories.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Self-referential relationship for hierarchical categories
    parent = relationship("ProductCategory", remote_side=[id], backref="subcategories")
    # Relationship with products
    products = relationship("Product", back_populates="category")
    
    def __repr__(self) -> str:
        return f"<ProductCategory {self.name}>"


class Product(Base):
    """Model for products in the catalog."""
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255))
    description = Column(Text)
    category_id = Column(Integer, ForeignKey("product_categories.id"))
    base_price = Column(Float)
    sku = Column(String(50), unique=True)
    image_url = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Additional product attributes
    specs = Column(JSON, nullable=True)  # Technical specifications
    benefits = Column(JSON, nullable=True)  # Key benefits/value props
    target_audience = Column(JSON, nullable=True)  # Target customer segments
    
    # Relationships
    category = relationship("ProductCategory", back_populates="products")
    features = relationship("ProductFeature", back_populates="product", cascade="all, delete-orphan")
    recommendations = relationship("ProductRecommendation", foreign_keys="ProductRecommendation.product_id", back_populates="product")
    upselling_opportunities = relationship("UpsellingOpportunity", foreign_keys="UpsellingOpportunity.base_product_id", back_populates="base_product")
    
    def __repr__(self) -> str:
        return f"<Product {self.name}>"


class ProductFeature(Base):
    """Model for product features."""
    __tablename__ = "product_features"
    
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    name = Column(String(100))
    description = Column(Text)
    is_highlighted = Column(Boolean, default=False)
    
    # Relationship
    product = relationship("Product", back_populates="features")
    
    def __repr__(self) -> str:
        return f"<ProductFeature {self.name} for {self.product.name}>"


class ProductRecommendation(Base):
    """Model for storing product recommendations."""
    __tablename__ = "product_recommendations"
    
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    recommended_at = Column(DateTime, default=datetime.utcnow)
    confidence_score = Column(Float, default=0.0)  # 0.0 to 1.0
    reasons = Column(JSON, nullable=True)  # List of reasons for the recommendation
    was_accepted = Column(Boolean, nullable=True)  # Whether the lead accepted the recommendation
    context = Column(Text, nullable=True)  # Conversation context when recommendation was made
    
    # Relationships
    lead = relationship("Lead")
    product = relationship("Product", foreign_keys=[product_id], back_populates="recommendations")
    
    def __repr__(self) -> str:
        return f"<ProductRecommendation {self.product.name} for {self.lead.email}>"


class UpsellingOpportunity(Base):
    """Model for storing upselling and cross-selling opportunities."""
    __tablename__ = "upselling_opportunities"
    
    id = Column(Integer, primary_key=True, index=True)
    base_product_id = Column(Integer, ForeignKey("products.id"))
    upsell_product_id = Column(Integer, ForeignKey("products.id"))
    opportunity_type = Column(String(20))  # "upsell", "cross-sell", "bundle"
    description = Column(Text)
    discount_percentage = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    base_product = relationship("Product", foreign_keys=[base_product_id], back_populates="upselling_opportunities")
    upsell_product = relationship("Product", foreign_keys=[upsell_product_id])
    
    def __repr__(self) -> str:
        return f"<UpsellingOpportunity {self.opportunity_type}: {self.base_product.name} -> {self.upsell_product.name}>"


class UserPreference(Base):
    """Model for storing user preferences and interests."""
    __tablename__ = "user_preferences"
    
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    preference_type = Column(String(50))  # "feature", "category", "price_range", etc.
    preference_value = Column(String(255))
    preference_strength = Column(Float, default=0.5)  # 0.0 to 1.0
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    lead = relationship("Lead")
    
    def __repr__(self) -> str:
        return f"<UserPreference {self.preference_type}:{self.preference_value} for {self.lead.email}>"


class ComplianceRiskCategory(str, Enum):
    """Enumeration of compliance risk categories."""
    ILLEGAL_ACTIVITY = "illegal_activity"
    PRIVACY_VIOLATION = "privacy_violation"
    FINANCIAL_FRAUD = "financial_fraud"
    DISCRIMINATION = "discrimination"
    HARASSMENT = "harassment"
    INAPPROPRIATE_CONTENT = "inappropriate_content"
    OTHER = "other"


class ComplianceLog(Base):
    """Model for storing compliance-related interactions."""
    __tablename__ = "compliance_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    risk_category = Column(SQLAEnum(ComplianceRiskCategory))
    message_content = Column(Text)
    detected_phrases = Column(JSON, nullable=True)  # List of detected risky phrases
    action_taken = Column(String(100))  # e.g., "escalated", "blocked", "warned"
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    lead = relationship("Lead")
    conversation = relationship("Conversation")
    
    def __repr__(self) -> str:
        return f"<ComplianceLog {self.risk_category} for {self.lead.email}>" 