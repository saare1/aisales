import logging
import re
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.db.models import Lead, Conversation

# Configure logging
logger = logging.getLogger(__name__)

# Try to import sentiment analysis libraries
try:
    import nltk
    from nltk.sentiment.vader import SentimentIntensityAnalyzer
    nltk.download('vader_lexicon', quiet=True)
    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False
    logger.warning("NLTK not available. Falling back to rule-based sentiment analysis.")


class SentimentAnalyzer:
    """
    Service for analyzing sentiment in lead messages and adjusting AI responses accordingly.
    """
    
    # Sentiment thresholds
    SENTIMENT_THRESHOLDS = {
        "positive": 0.05,    # Compound score > 0.05 is positive
        "negative": -0.05,   # Compound score < -0.05 is negative
        "neutral": 0.0       # Everything else is neutral
    }
    
    # Response tone modifiers based on sentiment
    TONE_MODIFIERS = {
        "positive": {
            "greeting": "It's great to hear from you! ",
            "closing": "I'm looking forward to our continued conversation!",
            "style": "enthusiastic and matching your energy"
        },
        "negative": {
            "greeting": "I understand your concerns. ",
            "closing": "I'm here to help address any issues you have.",
            "style": "empathetic and understanding"
        },
        "neutral": {
            "greeting": "Thank you for your message. ",
            "closing": "Please let me know if you have any questions.",
            "style": "balanced and professional"
        }
    }
    
    # Keywords for rule-based sentiment analysis (fallback if NLTK not available)
    POSITIVE_KEYWORDS = [
        "great", "good", "excellent", "amazing", "wonderful", "fantastic",
        "happy", "pleased", "satisfied", "love", "like", "enjoy",
        "thanks", "thank you", "appreciate", "helpful", "perfect",
        "excited", "looking forward", "interested", "yes", "sure"
    ]
    
    NEGATIVE_KEYWORDS = [
        "bad", "poor", "terrible", "awful", "horrible", "disappointing",
        "unhappy", "dissatisfied", "dislike", "hate", "annoying", "frustrating",
        "problem", "issue", "complaint", "wrong", "mistake", "error",
        "expensive", "costly", "waste", "difficult", "hard", "confusing",
        "no", "not", "cannot", "won't", "doesn't", "don't", "never", "fail"
    ]
    
    @staticmethod
    def analyze_sentiment(text: str) -> Dict[str, Any]:
        """
        Analyze the sentiment of a message.
        
        Args:
            text: The text to analyze
            
        Returns:
            Dictionary with sentiment scores and category
        """
        if NLTK_AVAILABLE:
            return SentimentAnalyzer._analyze_with_nltk(text)
        else:
            return SentimentAnalyzer._analyze_with_rules(text)
    
    @staticmethod
    def _analyze_with_nltk(text: str) -> Dict[str, Any]:
        """Analyze sentiment using NLTK's VADER."""
        sia = SentimentIntensityAnalyzer()
        scores = sia.polarity_scores(text)
        
        # Determine sentiment category based on compound score
        compound = scores['compound']
        if compound >= SentimentAnalyzer.SENTIMENT_THRESHOLDS["positive"]:
            category = "positive"
        elif compound <= SentimentAnalyzer.SENTIMENT_THRESHOLDS["negative"]:
            category = "negative"
        else:
            category = "neutral"
        
        return {
            "positive": scores["pos"],
            "negative": scores["neg"],
            "neutral": scores["neu"],
            "compound": compound,
            "category": category
        }
    
    @staticmethod
    def _analyze_with_rules(text: str) -> Dict[str, Any]:
        """Analyze sentiment using simple rule-based approach (fallback method)."""
        text_lower = text.lower()
        
        # Count occurrences of positive and negative keywords
        positive_count = sum(1 for word in SentimentAnalyzer.POSITIVE_KEYWORDS if word in text_lower)
        negative_count = sum(1 for word in SentimentAnalyzer.NEGATIVE_KEYWORDS if word in text_lower)
        
        # Calculate simple sentiment scores
        total = positive_count + negative_count
        if total == 0:
            # No sentiment words found, assume neutral
            positive = 0.0
            negative = 0.0
            neutral = 1.0
            compound = 0.0
            category = "neutral"
        else:
            positive = positive_count / total
            negative = negative_count / total
            neutral = 1.0 - (positive + negative)
            
            # Calculate a compound score similar to VADER (-1 to 1 scale)
            compound = (positive - negative)
            
            # Determine category
            if compound >= SentimentAnalyzer.SENTIMENT_THRESHOLDS["positive"]:
                category = "positive"
            elif compound <= SentimentAnalyzer.SENTIMENT_THRESHOLDS["negative"]:
                category = "negative"
            else:
                category = "neutral"
        
        return {
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
            "compound": compound,
            "category": category
        }
    
    @classmethod
    def analyze_and_store_sentiment(
        cls,
        conversation_id: int,
        text: str,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Analyze sentiment and store the result in the database.
        
        Args:
            conversation_id: ID of the conversation
            text: Text content to analyze
            db: Database session
            
        Returns:
            The sentiment analysis results
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the conversation
            conversation = db.query(Conversation).filter(
                Conversation.id == conversation_id
            ).first()
            
            if not conversation:
                logger.error(f"Conversation with ID {conversation_id} not found")
                return {}
            
            # Analyze sentiment
            sentiment = cls.analyze_sentiment(text)
            
            # Update the conversation with sentiment scores
            conversation.sentiment_score = sentiment["compound"]
            
            # Commit changes
            db.commit()
            
            return sentiment
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def get_lead_sentiment_history(
        cls,
        lead_id: int,
        limit: int = 10,
        db: Session = None
    ) -> List[Dict[str, Any]]:
        """
        Get the sentiment history for a lead.
        
        Args:
            lead_id: ID of the lead
            limit: Maximum number of records to return
            db: Database session
            
        Returns:
            List of sentiment records for the lead
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the lead's conversations
            conversations = db.query(Conversation).filter(
                Conversation.lead_id == lead_id,
                Conversation.is_from_lead == True,  # Only messages from the lead
                Conversation.sentiment_score.isnot(None)  # Only messages with sentiment scores
            ).order_by(Conversation.created_at.desc()).limit(limit).all()
            
            # Format the results
            results = []
            for conv in conversations:
                # Determine category from score
                score = conv.sentiment_score
                if score >= cls.SENTIMENT_THRESHOLDS["positive"]:
                    category = "positive"
                elif score <= cls.SENTIMENT_THRESHOLDS["negative"]:
                    category = "negative"
                else:
                    category = "neutral"
                
                results.append({
                    "conversation_id": conv.id,
                    "content": conv.content,
                    "created_at": conv.created_at.isoformat(),
                    "sentiment_score": score,
                    "category": category
                })
            
            return results
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def get_lead_overall_sentiment(
        cls,
        lead_id: int,
        days: int = 30,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Calculate the overall sentiment for a lead based on recent conversations.
        
        Args:
            lead_id: ID of the lead
            days: Number of days to analyze
            db: Database session
            
        Returns:
            Dictionary with overall sentiment metrics
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Define the date range
            end_date = datetime.utcnow()
            start_date = end_date - datetime.timedelta(days=days)
            
            # Get the lead's conversations within the date range
            conversations = db.query(Conversation).filter(
                Conversation.lead_id == lead_id,
                Conversation.is_from_lead == True,  # Only messages from the lead
                Conversation.sentiment_score.isnot(None),  # Only messages with sentiment scores
                Conversation.created_at.between(start_date, end_date)
            ).all()
            
            if not conversations:
                return {
                    "lead_id": lead_id,
                    "average_sentiment": 0.0,
                    "sentiment_trend": "neutral",
                    "message_count": 0,
                    "period_days": days
                }
            
            # Calculate average sentiment
            total_score = sum(conv.sentiment_score for conv in conversations)
            average_sentiment = total_score / len(conversations)
            
            # Determine sentiment trend (are they getting more positive or negative?)
            if len(conversations) >= 2:
                sorted_convs = sorted(conversations, key=lambda c: c.created_at)
                early_convs = sorted_convs[:len(sorted_convs)//2]
                recent_convs = sorted_convs[len(sorted_convs)//2:]
                
                early_avg = sum(c.sentiment_score for c in early_convs) / len(early_convs)
                recent_avg = sum(c.sentiment_score for c in recent_convs) / len(recent_convs)
                
                if recent_avg > early_avg + 0.1:
                    trend = "improving"
                elif recent_avg < early_avg - 0.1:
                    trend = "declining"
                else:
                    trend = "stable"
            else:
                trend = "insufficient data"
            
            # Determine overall category
            if average_sentiment >= cls.SENTIMENT_THRESHOLDS["positive"]:
                category = "positive"
            elif average_sentiment <= cls.SENTIMENT_THRESHOLDS["negative"]:
                category = "negative"
            else:
                category = "neutral"
            
            return {
                "lead_id": lead_id,
                "average_sentiment": average_sentiment,
                "category": category,
                "sentiment_trend": trend,
                "message_count": len(conversations),
                "period_days": days
            }
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def modify_response_for_sentiment(
        cls,
        response_text: str,
        lead_sentiment: str
    ) -> str:
        """
        Modify the agent's response based on the lead's sentiment.
        
        Args:
            response_text: The original response text
            lead_sentiment: The lead's sentiment category (positive, negative, neutral)
            
        Returns:
            Modified response text
        """
        # Get the appropriate tone modifiers
        modifiers = cls.TONE_MODIFIERS.get(lead_sentiment, cls.TONE_MODIFIERS["neutral"])
        
        # Check if the response already has a greeting
        has_greeting = bool(re.match(r'^(hi|hello|hey|greetings|good (morning|afternoon|evening))', 
                                     response_text.lower()))
        
        # Modify the response
        if has_greeting:
            # Don't add another greeting if one exists
            modified_response = response_text
        else:
            # Add a sentiment-appropriate greeting
            modified_response = modifiers["greeting"] + response_text
        
        # Add a sentiment-appropriate closing if the response doesn't already have one
        if not (response_text.rstrip().endswith('.') or 
                response_text.rstrip().endswith('!') or 
                response_text.rstrip().endswith('?')):
            modified_response += ". "
        else:
            modified_response += " "
        
        # Add closing
        modified_response += modifiers["closing"]
        
        return modified_response 