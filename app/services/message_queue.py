import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from threading import Lock
import heapq

from app.db.database import get_db_session
from app.db.models import Lead, Conversation, LeadStatus, ConversationChannel
from app.services.sentiment_analyzer import SentimentAnalyzer

# Configure logging
logger = logging.getLogger(__name__)


class MessagePriority:
    """
    Constants for message priority levels. Higher numbers indicate higher priority.
    """
    LOW = 1        # Cold leads, routine follow-ups
    MEDIUM = 2     # Warm leads, regular conversations
    HIGH = 3       # Hot leads, buying signals, objections
    URGENT = 4     # Critical responses, closing opportunities
    IMMEDIATE = 5  # Explicit purchase intent, urgent issues


class QueuedMessage:
    """
    Represents a message in the queue that needs to be processed.
    """
    
    def __init__(
        self, 
        lead_id: int, 
        lead_email: str,
        message_id: int,
        content: str,
        channel: ConversationChannel,
        priority: int,
        timestamp: datetime,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.lead_id = lead_id
        self.lead_email = lead_email
        self.message_id = message_id
        self.content = content
        self.channel = channel
        self.priority = priority
        self.timestamp = timestamp
        self.metadata = metadata or {}
    
    def __lt__(self, other):
        """
        Custom comparison for priority queue.
        First compare by priority, then by timestamp (older first).
        """
        if self.priority != other.priority:
            return self.priority > other.priority  # Higher priority first
        return self.timestamp < other.timestamp  # Then older messages first


class MessageQueue:
    """
    Service for prioritizing and queuing incoming messages from multiple leads.
    Ensures messages are processed in order of priority rather than just FIFO.
    """
    
    def __init__(self):
        """Initialize the message queue."""
        self._queue = []  # Priority queue (implemented as a heap)
        self._lock = Lock()  # Thread-safe operations
    
    def enqueue(self, message: QueuedMessage) -> bool:
        """
        Add a message to the queue.
        
        Args:
            message: The message to add to the queue
            
        Returns:
            True if the message was added successfully
        """
        with self._lock:
            try:
                heapq.heappush(self._queue, message)
                logger.info(f"Enqueued message from {message.lead_email} with priority {message.priority}")
                return True
            except Exception as e:
                logger.error(f"Error enqueuing message: {str(e)}")
                return False
    
    def dequeue(self) -> Optional[QueuedMessage]:
        """
        Get the highest priority message from the queue.
        
        Returns:
            The highest priority message, or None if the queue is empty
        """
        with self._lock:
            if not self._queue:
                return None
            
            message = heapq.heappop(self._queue)
            logger.info(f"Dequeued message from {message.lead_email}")
            return message
    
    def peek(self) -> Optional[QueuedMessage]:
        """
        Look at the highest priority message without removing it.
        
        Returns:
            The highest priority message, or None if the queue is empty
        """
        with self._lock:
            if not self._queue:
                return None
            return self._queue[0]
    
    def size(self) -> int:
        """
        Get the current size of the queue.
        
        Returns:
            The number of messages in the queue
        """
        with self._lock:
            return len(self._queue)
    
    def clear(self) -> None:
        """Clear all messages from the queue."""
        with self._lock:
            self._queue = []
            logger.info("Message queue cleared")
    
    @staticmethod
    def calculate_priority(
        lead: Lead,
        message_content: str,
        sentiment_score: Optional[float] = None,
        db: Session = None
    ) -> int:
        """
        Calculate the priority for a message based on various factors.
        
        Args:
            lead: The lead who sent the message
            message_content: The content of the message
            sentiment_score: Optional sentiment score (-1 to 1)
            db: Database session
            
        Returns:
            Priority level (1-5)
        """
        # Start with a base priority
        priority = MessagePriority.MEDIUM
        
        # Adjust based on lead status
        status_priority = {
            LeadStatus.NEW: MessagePriority.HIGH,  # New leads get high priority
            LeadStatus.QUALIFIED: MessagePriority.HIGH,
            LeadStatus.NEGOTIATING: MessagePriority.URGENT,  # Leads close to conversion get urgent priority
            LeadStatus.MEETING_SCHEDULED: MessagePriority.HIGH,
        }
        
        priority = max(priority, status_priority.get(lead.status, priority))
        
        # Adjust based on lead temperature
        if lead.temperature == "hot":
            priority = max(priority, MessagePriority.HIGH)
        elif lead.temperature == "warm":
            priority = max(priority, MessagePriority.MEDIUM)
        
        # Check for urgent keywords in the message
        urgent_keywords = ["urgent", "asap", "emergency", "immediately", "buy now", 
                           "purchase now", "sign up now", "ready to proceed"]
        
        if any(keyword in message_content.lower() for keyword in urgent_keywords):
            priority = max(priority, MessagePriority.URGENT)
        
        # If it's the first message, give it higher priority
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            conversation_count = db.query(Conversation).filter(
                Conversation.lead_id == lead.id,
                Conversation.is_from_lead == True
            ).count()
            
            if conversation_count <= 1:  # First or second message
                priority = max(priority, MessagePriority.HIGH)
        finally:
            if close_db:
                db.close()
        
        # Adjust based on sentiment
        if sentiment_score is not None:
            if sentiment_score <= -0.5:  # Very negative sentiment
                priority = max(priority, MessagePriority.URGENT)  # Prioritize addressing negative sentiment
            elif sentiment_score <= -0.2:  # Moderately negative
                priority = max(priority, MessagePriority.HIGH)
        
        # Check for explicit buying signals
        buying_signals = ["ready to buy", "credit card", "payment", "purchase", 
                         "sign contract", "let's do it", "move forward"]
        
        if any(signal in message_content.lower() for signal in buying_signals):
            priority = MessagePriority.IMMEDIATE
        
        return priority
    
    @classmethod
    def process_incoming_message(
        cls,
        message_queue: 'MessageQueue',
        lead_email: str,
        content: str,
        channel: ConversationChannel,
        db: Session = None
    ) -> Optional[int]:
        """
        Process an incoming message and add it to the queue.
        
        Args:
            message_queue: The message queue to add the message to
            lead_email: Email of the lead
            content: Content of the message
            channel: Channel through which the message was received
            db: Database session
            
        Returns:
            The message ID if successful, None otherwise
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the lead
            lead = db.query(Lead).filter(Lead.email == lead_email).first()
            if not lead:
                logger.error(f"Lead with email {lead_email} not found")
                return None
            
            # Store the message
            new_message = Conversation(
                lead_id=lead.id,
                content=content,
                is_from_lead=True,
                channel=channel,
                created_at=datetime.utcnow()
            )
            
            db.add(new_message)
            db.commit()
            db.refresh(new_message)
            
            # Update the lead's last_contact timestamp
            lead.last_contact = datetime.utcnow()
            db.commit()
            
            # Analyze sentiment
            sentiment = SentimentAnalyzer.analyze_sentiment(content)
            sentiment_score = sentiment["compound"]
            
            # Update the message with sentiment information
            new_message.sentiment_score = sentiment_score
            db.commit()
            
            # Calculate priority
            priority = cls.calculate_priority(lead, content, sentiment_score, db)
            
            # Create a queued message
            queued_message = QueuedMessage(
                lead_id=lead.id,
                lead_email=lead_email,
                message_id=new_message.id,
                content=content,
                channel=channel,
                priority=priority,
                timestamp=new_message.created_at,
                metadata={
                    "sentiment": sentiment,
                    "lead_status": lead.status.value,
                    "lead_temperature": lead.temperature if hasattr(lead, "temperature") else "unknown"
                }
            )
            
            # Add to the queue
            message_queue.enqueue(queued_message)
            
            return new_message.id
        except Exception as e:
            if db:
                db.rollback()
            logger.error(f"Error processing incoming message: {str(e)}")
            return None
        finally:
            if close_db and db:
                db.close()
    
    @classmethod
    def get_queue_stats(cls, message_queue: 'MessageQueue') -> Dict[str, Any]:
        """
        Get statistics about the current message queue.
        
        Args:
            message_queue: The message queue to analyze
            
        Returns:
            Dictionary with queue statistics
        """
        with message_queue._lock:
            if not message_queue._queue:
                return {
                    "total_messages": 0,
                    "priority_distribution": {
                        "immediate": 0,
                        "urgent": 0,
                        "high": 0,
                        "medium": 0,
                        "low": 0
                    },
                    "oldest_message": None,
                    "newest_message": None
                }
            
            # Count messages by priority
            priority_counts = {
                MessagePriority.IMMEDIATE: 0,
                MessagePriority.URGENT: 0,
                MessagePriority.HIGH: 0,
                MessagePriority.MEDIUM: 0,
                MessagePriority.LOW: 0
            }
            
            for msg in message_queue._queue:
                priority_counts[msg.priority] = priority_counts.get(msg.priority, 0) + 1
            
            # Find oldest and newest messages
            timestamps = [msg.timestamp for msg in message_queue._queue]
            oldest = min(timestamps)
            newest = max(timestamps)
            
            return {
                "total_messages": len(message_queue._queue),
                "priority_distribution": {
                    "immediate": priority_counts[MessagePriority.IMMEDIATE],
                    "urgent": priority_counts[MessagePriority.URGENT],
                    "high": priority_counts[MessagePriority.HIGH],
                    "medium": priority_counts[MessagePriority.MEDIUM],
                    "low": priority_counts[MessagePriority.LOW]
                },
                "oldest_message": oldest.isoformat(),
                "newest_message": newest.isoformat()
            }
    
    @classmethod
    def get_pending_messages_for_lead(
        cls,
        message_queue: 'MessageQueue',
        lead_id: int
    ) -> List[QueuedMessage]:
        """
        Get all pending messages for a specific lead.
        
        Args:
            message_queue: The message queue to search
            lead_id: ID of the lead
            
        Returns:
            List of pending messages for the lead
        """
        with message_queue._lock:
            return [msg for msg in message_queue._queue if msg.lead_id == lead_id]
    
    @classmethod
    def remove_messages_for_lead(
        cls,
        message_queue: 'MessageQueue',
        lead_id: int
    ) -> int:
        """
        Remove all messages for a specific lead from the queue.
        
        Args:
            message_queue: The message queue to modify
            lead_id: ID of the lead
            
        Returns:
            Number of messages removed
        """
        with message_queue._lock:
            original_size = len(message_queue._queue)
            message_queue._queue = [msg for msg in message_queue._queue if msg.lead_id != lead_id]
            
            # Rebuild the heap structure
            heapq.heapify(message_queue._queue)
            
            removed_count = original_size - len(message_queue._queue)
            logger.info(f"Removed {removed_count} messages for lead {lead_id}")
            
            return removed_count


# Initialize the global message queue
global_message_queue = MessageQueue() 