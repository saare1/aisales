import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set, Any
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.db.models import Lead, Conversation, LeadStatus, LeadTemperature, Interaction, BusinessSettings
from app.services.memory import MemoryManager

# Configure logging
logger = logging.getLogger(__name__)

# Constants for scoring
BUYING_SIGNAL_KEYWORDS = {
    "buy", "purchase", "interested", "when can", "how soon", "price", "cost", 
    "demo", "trial", "sign up", "subscribe", "payment", "start", "begin",
    "how does it work", "ready to", "move forward", "next step", "let's do it",
    "credit card", "invoice", "contract", "agreement", "sounds good"
}

OBJECTION_KEYWORDS = {
    "expensive", "costly", "budget", "price", "afford", "not sure", "think about", 
    "competitor", "alternative", "not ready", "later", "wait", "too much", 
    "too long", "delay", "postpone", "concern", "worried", "issue", "problem"
}

QUESTION_ANSWER_INDICATORS = {
    "my budget is", "we need", "we're looking for", "I need", "I'm looking for",
    "our company", "our team", "our goal", "my goal", "our timeline", "my timeline",
    "I can", "we can", "I will", "we will", "I have", "we have", "our current"
}


class LeadScorer:
    """
    Service for evaluating and scoring leads based on various factors.
    
    This service provides:
    1. Lead scoring based on interactions, demographics, and behavior
    2. Determination of lead temperature (hot, warm, cool, cold)
    3. Identification of high-potential leads
    """
    
    # Default weights for different scoring factors
    DEFAULT_WEIGHTS = {
        "interaction_recency": 25,     # How recently the lead interacted
        "interaction_frequency": 20,   # How frequently the lead interacts
        "interaction_engagement": 15,  # Quality of the interactions (replies, questions asked)
        "demographic_match": 15,       # How well lead matches target demographics
        "budget_indication": 15,       # Indications of budget/willingness to pay
        "initial_interest": 10         # Level of interest shown in first contact
    }
    
    # Score thresholds for lead temperature
    TEMPERATURE_THRESHOLDS = {
        "hot": 80,    # Scores 80-100
        "warm": 60,   # Scores 60-79
        "cool": 40,   # Scores 40-59
        "cold": 0     # Scores 0-39
    }
    
    def __init__(self, custom_weights: Optional[Dict[str, float]] = None):
        """
        Initialize the LeadScorer with optional custom weights.
        
        Args:
            custom_weights: Optional custom weights for scoring factors
        """
        self.weights = custom_weights or self.DEFAULT_WEIGHTS
        
        # Normalize weights to ensure they sum to 100
        weight_sum = sum(self.weights.values())
        if weight_sum != 100:
            for key in self.weights:
                self.weights[key] = (self.weights[key] / weight_sum) * 100
    
    def score_lead(self, lead_id: int, db: Session = None) -> float:
        """
        Calculate a comprehensive score for a lead.
        
        Args:
            lead_id: The ID of the lead to score
            db: Database session
            
        Returns:
            The lead's score (0-100)
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the lead
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            
            if not lead:
                logger.error(f"Could not find lead with ID {lead_id}")
                return 0
            
            # Get business settings if available
            business_settings = db.query(BusinessSettings).filter(
                BusinessSettings.business_id == lead.business_id
            ).first() if lead.business_id else None
            
            # Get lead interactions
            interactions = db.query(Interaction).filter(
                Interaction.lead_id == lead_id
            ).order_by(Interaction.timestamp.desc()).all()
            
            # Calculate individual scores
            recency_score = self._calculate_recency_score(interactions)
            frequency_score = self._calculate_frequency_score(interactions)
            engagement_score = self._calculate_engagement_score(interactions)
            demographic_score = self._calculate_demographic_score(lead, business_settings)
            budget_score = self._calculate_budget_score(lead, interactions)
            interest_score = self._calculate_initial_interest_score(lead, interactions)
            
            # Calculate weighted average
            final_score = (
                (recency_score * self.weights["interaction_recency"]) +
                (frequency_score * self.weights["interaction_frequency"]) +
                (engagement_score * self.weights["interaction_engagement"]) +
                (demographic_score * self.weights["demographic_match"]) +
                (budget_score * self.weights["budget_indication"]) +
                (interest_score * self.weights["initial_interest"])
            ) / 100
            
            # Round to nearest integer and ensure within 0-100 range
            final_score = round(max(0, min(100, final_score)))
            
            # Update lead's score in database
            lead.score = final_score
            lead.score_updated_at = datetime.utcnow()
            db.commit()
            
            logger.info(f"Scored lead {lead_id} with score {final_score}")
            
            return final_score
        except Exception as e:
            if db:
                db.rollback()
            logger.error(f"Error scoring lead: {str(e)}")
            return 0
        finally:
            if close_db and db:
                db.close()
    
    def _calculate_recency_score(self, interactions: List[Interaction]) -> float:
        """
        Calculate a score based on how recently the lead interacted.
        
        Args:
            interactions: List of lead interactions
            
        Returns:
            Recency score (0-100)
        """
        if not interactions:
            return 0
        
        # Get the most recent interaction
        most_recent = interactions[0].timestamp
        now = datetime.utcnow()
        days_since = (now - most_recent).days
        
        # Score based on recency
        if days_since <= 1:  # Within last day
            return 100
        elif days_since <= 3:  # Within last 3 days
            return 80
        elif days_since <= 7:  # Within last week
            return 60
        elif days_since <= 14:  # Within last 2 weeks
            return 40
        elif days_since <= 30:  # Within last month
            return 20
        else:  # More than a month
            return 0
    
    def _calculate_frequency_score(self, interactions: List[Interaction]) -> float:
        """
        Calculate a score based on how frequently the lead interacts.
        
        Args:
            interactions: List of lead interactions
            
        Returns:
            Frequency score (0-100)
        """
        if not interactions:
            return 0
        
        # Count interactions in the last 30 days
        now = datetime.utcnow()
        thirty_days_ago = now - timedelta(days=30)
        recent_interactions = [i for i in interactions if i.timestamp >= thirty_days_ago]
        count = len(recent_interactions)
        
        # Score based on interaction frequency
        if count >= 10:  # Very frequent interaction
            return 100
        elif count >= 7:  # High interaction
            return 80
        elif count >= 5:  # Good interaction
            return 60
        elif count >= 3:  # Moderate interaction
            return 40
        elif count >= 1:  # Low interaction
            return 20
        else:  # No recent interaction
            return 0
    
    def _calculate_engagement_score(self, interactions: List[Interaction]) -> float:
        """
        Calculate a score based on the quality of lead engagement.
        
        Args:
            interactions: List of lead interactions
            
        Returns:
            Engagement score (0-100)
        """
        if not interactions:
            return 0
        
        # Analyze interaction content for engagement indicators
        total_interactions = len(interactions)
        positive_indicators = 0
        
        for interaction in interactions:
            # Check for positive engagement indicators
            if interaction.is_question:
                positive_indicators += 1
            if interaction.has_positive_sentiment:
                positive_indicators += 1
            if interaction.response_time_seconds and interaction.response_time_seconds < 3600:  # Responded within an hour
                positive_indicators += 1
        
        # Calculate engagement ratio
        engagement_ratio = positive_indicators / (total_interactions * 3) if total_interactions > 0 else 0
        
        # Convert to 0-100 score
        return engagement_ratio * 100
    
    def _calculate_demographic_score(self, lead: Lead, business_settings: Optional[BusinessSettings]) -> float:
        """
        Calculate a score based on how well the lead matches target demographics.
        
        Args:
            lead: The lead object
            business_settings: Business settings with target demographics
            
        Returns:
            Demographic match score (0-100)
        """
        if not business_settings or not business_settings.target_demographics:
            return 50  # Neutral score if no target demographics
        
        # Convert target demographics to dictionary for easier matching
        try:
            target_demographics = business_settings.target_demographics
            
            # Count matching demographic factors
            total_factors = len(target_demographics)
            matching_factors = 0
            
            # Check each demographic factor
            for factor, value in target_demographics.items():
                lead_value = getattr(lead, factor, None)
                if lead_value and lead_value == value:
                    matching_factors += 1
            
            # Calculate match percentage
            match_percentage = (matching_factors / total_factors) * 100 if total_factors > 0 else 50
            
            return match_percentage
        except Exception as e:
            logger.error(f"Error calculating demographic score: {str(e)}")
            return 50
    
    def _calculate_budget_score(self, lead: Lead, interactions: List[Interaction]) -> float:
        """
        Calculate a score based on budget indications.
        
        Args:
            lead: The lead object
            interactions: List of lead interactions
            
        Returns:
            Budget indication score (0-100)
        """
        # Start with a baseline score
        score = 50
        
        # Check if lead has explicitly provided budget information
        if lead.budget_amount is not None and lead.budget_amount > 0:
            score = min(100, 60 + (lead.budget_amount / 1000))  # Scale based on budget amount
        
        # Analyze interactions for budget-related keywords
        budget_keywords = ["price", "cost", "budget", "afford", "investment", "spend", "package", "plan"]
        budget_mentions = 0
        
        for interaction in interactions:
            if interaction.content:
                for keyword in budget_keywords:
                    if keyword in interaction.content.lower():
                        budget_mentions += 1
        
        # Adjust score based on budget mentions
        if budget_mentions >= 3:
            score = min(100, score + 30)
        elif budget_mentions >= 1:
            score = min(100, score + 15)
        
        return score
    
    def _calculate_initial_interest_score(self, lead: Lead, interactions: List[Interaction]) -> float:
        """
        Calculate a score based on the initial interest level.
        
        Args:
            lead: The lead object
            interactions: List of lead interactions
            
        Returns:
            Initial interest score (0-100)
        """
        if not interactions:
            return 0
        
        # Get the first interaction
        first_interactions = sorted(interactions, key=lambda x: x.timestamp)
        if not first_interactions:
            return 0
            
        first = first_interactions[0]
        
        # Calculate score based on first interaction
        score = 0
        
        # Check lead source quality
        if lead.source == "referral":
            score += 40
        elif lead.source == "website_contact":
            score += 30
        elif lead.source == "social_media":
            score += 20
        else:
            score += 10
        
        # Check first message content
        if first.is_question:
            score += 20
        if first.has_positive_sentiment:
            score += 20
        if len(first.content or "") > 100:  # Detailed first message
            score += 20
        
        return min(100, score)
    
    def determine_lead_temperature(self, score: float) -> str:
        """
        Determine the temperature category of a lead based on score.
        
        Args:
            score: The lead score (0-100)
            
        Returns:
            Temperature category: "hot", "warm", "cool", or "cold"
        """
        if score >= self.TEMPERATURE_THRESHOLDS["hot"]:
            return "hot"
        elif score >= self.TEMPERATURE_THRESHOLDS["warm"]:
            return "warm"
        elif score >= self.TEMPERATURE_THRESHOLDS["cool"]:
            return "cool"
        else:
            return "cold"
    
    def identify_high_potential_leads(
        self, 
        business_id: Optional[int] = None,
        min_score: float = 60,
        limit: int = 10,
        db: Session = None
    ) -> List[Dict[str, Any]]:
        """
        Identify leads with high potential for conversion.
        
        Args:
            business_id: Optional business ID to filter leads
            min_score: Minimum score threshold
            limit: Maximum number of leads to return
            db: Database session
            
        Returns:
            List of high-potential leads with their scores
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Query for leads
            query = db.query(Lead).filter(Lead.score >= min_score)
            
            if business_id:
                query = query.filter(Lead.business_id == business_id)
            
            # Order by score (highest first)
            leads = query.order_by(Lead.score.desc()).limit(limit).all()
            
            # Format the results
            high_potential_leads = []
            for lead in leads:
                high_potential_leads.append({
                    "lead_id": lead.id,
                    "name": lead.name,
                    "email": lead.email,
                    "phone": lead.phone,
                    "score": lead.score,
                    "temperature": self.determine_lead_temperature(lead.score),
                    "last_interaction": lead.last_interaction_date.isoformat() if lead.last_interaction_date else None,
                    "days_in_pipeline": (datetime.utcnow() - lead.created_at).days if lead.created_at else None
                })
            
            return high_potential_leads
        finally:
            if close_db:
                db.close()
    
    def get_score_breakdown(self, lead_id: int, db: Session = None) -> Dict[str, Any]:
        """
        Get a detailed breakdown of a lead's score components.
        
        Args:
            lead_id: The ID of the lead
            db: Database session
            
        Returns:
            Dictionary with score components and their values
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the lead
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            
            if not lead:
                logger.error(f"Could not find lead with ID {lead_id}")
                return {}
            
            # Get business settings if available
            business_settings = db.query(BusinessSettings).filter(
                BusinessSettings.business_id == lead.business_id
            ).first() if lead.business_id else None
            
            # Get lead interactions
            interactions = db.query(Interaction).filter(
                Interaction.lead_id == lead_id
            ).order_by(Interaction.timestamp.desc()).all()
            
            # Calculate individual scores
            recency_score = self._calculate_recency_score(interactions)
            frequency_score = self._calculate_frequency_score(interactions)
            engagement_score = self._calculate_engagement_score(interactions)
            demographic_score = self._calculate_demographic_score(lead, business_settings)
            budget_score = self._calculate_budget_score(lead, interactions)
            interest_score = self._calculate_initial_interest_score(lead, interactions)
            
            # Create score breakdown
            return {
                "lead_id": lead_id,
                "total_score": lead.score,
                "temperature": self.determine_lead_temperature(lead.score),
                "score_updated_at": lead.score_updated_at.isoformat() if lead.score_updated_at else None,
                "components": {
                    "interaction_recency": {
                        "score": recency_score,
                        "weight": self.weights["interaction_recency"],
                        "weighted_score": (recency_score * self.weights["interaction_recency"]) / 100
                    },
                    "interaction_frequency": {
                        "score": frequency_score,
                        "weight": self.weights["interaction_frequency"],
                        "weighted_score": (frequency_score * self.weights["interaction_frequency"]) / 100
                    },
                    "interaction_engagement": {
                        "score": engagement_score,
                        "weight": self.weights["interaction_engagement"],
                        "weighted_score": (engagement_score * self.weights["interaction_engagement"]) / 100
                    },
                    "demographic_match": {
                        "score": demographic_score,
                        "weight": self.weights["demographic_match"],
                        "weighted_score": (demographic_score * self.weights["demographic_match"]) / 100
                    },
                    "budget_indication": {
                        "score": budget_score,
                        "weight": self.weights["budget_indication"],
                        "weighted_score": (budget_score * self.weights["budget_indication"]) / 100
                    },
                    "initial_interest": {
                        "score": interest_score,
                        "weight": self.weights["initial_interest"],
                        "weighted_score": (interest_score * self.weights["initial_interest"]) / 100
                    }
                }
            }
        finally:
            if close_db:
                db.close()
    
    def update_all_lead_scores(
        self,
        business_id: Optional[int] = None,
        days_since_update: int = 7,
        db: Session = None
    ) -> Tuple[int, Dict[str, int]]:
        """
        Update scores for all leads that haven't been updated recently.
        
        Args:
            business_id: Optional business ID to filter leads
            days_since_update: Only update leads not scored in this many days
            db: Database session
            
        Returns:
            Tuple of (number of leads updated, counts by temperature)
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the cutoff date
            cutoff_date = datetime.utcnow() - timedelta(days=days_since_update)
            
            # Query for leads that need scoring
            query = db.query(Lead).filter(
                (Lead.score_updated_at == None) | (Lead.score_updated_at <= cutoff_date)
            )
            
            if business_id:
                query = query.filter(Lead.business_id == business_id)
            
            # Get leads to update
            leads_to_update = query.all()
            
            # Update each lead's score
            updated_count = 0
            temperature_counts = {"hot": 0, "warm": 0, "cool": 0, "cold": 0}
            
            for lead in leads_to_update:
                score = self.score_lead(lead.id, db)
                temperature = self.determine_lead_temperature(score)
                temperature_counts[temperature] += 1
                updated_count += 1
            
            logger.info(f"Updated scores for {updated_count} leads")
            
            return updated_count, temperature_counts
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def analyze_message_for_signals(
        cls, 
        message_content: str, 
        lead_id: int,
        is_from_lead: bool,
        db: Session = None
    ) -> Dict[str, bool]:
        """
        Analyze a message for buying signals, objections, and question answers.
        
        Args:
            message_content: The content of the message to analyze
            lead_id: The ID of the lead who sent or received the message
            is_from_lead: True if the message is from the lead, False if from the agent
            db: Database session
            
        Returns:
            Dictionary with analysis results
        """
        if not is_from_lead:
            # If message is from agent, there's no buying signal or objection
            return {
                "contains_buying_signal": False,
                "contains_objection": False,
                "question_answered": False
            }
        
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the lead
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if not lead:
                logger.error(f"Could not find lead with ID {lead_id}")
                return {
                    "contains_buying_signal": False,
                    "contains_objection": False,
                    "question_answered": False
                }
            
            # Convert message to lowercase for easier matching
            message_lower = message_content.lower()
            
            # Check for buying signals
            contains_buying_signal = cls._has_buying_signals(message_lower)
            
            # Check for objections
            contains_objection = cls._has_objections(message_lower)
            
            # Check for question answers
            question_answered = cls._has_question_answers(message_lower)
            
            # Update lead record if signals are found
            if contains_buying_signal:
                lead.buying_signals += 1
            
            if question_answered:
                lead.question_responses += 1
            
            # Update lead's last interaction length
            lead.last_interaction_length = len(message_content)
            
            db.commit()
            
            return {
                "contains_buying_signal": contains_buying_signal,
                "contains_objection": contains_objection,
                "question_answered": question_answered
            }
        finally:
            if close_db:
                db.close()
    
    @staticmethod
    def _has_buying_signals(message: str) -> bool:
        """Check if the message contains buying signals."""
        return any(signal in message for signal in BUYING_SIGNAL_KEYWORDS)
    
    @staticmethod
    def _has_objections(message: str) -> bool:
        """Check if the message contains objections."""
        return any(objection in message for objection in OBJECTION_KEYWORDS)
    
    @staticmethod
    def _has_question_answers(message: str) -> bool:
        """Check if the message contains answers to qualifying questions."""
        return any(indicator in message for indicator in QUESTION_ANSWER_INDICATORS)
    
    @classmethod
    def find_leads_needing_followup(cls, db: Session = None) -> List[Lead]:
        """
        Find leads that need follow-up based on their temperature.
        
        Args:
            db: Database session
            
        Returns:
            List of leads needing follow-up
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            now = datetime.utcnow()
            
            # Define followup thresholds based on temperature
            hot_threshold = now - timedelta(hours=6)
            warm_threshold = now - timedelta(hours=24)
            cold_threshold = now - timedelta(days=3)
            
            # Find hot leads needing followup
            hot_leads = (
                db.query(Lead)
                .filter(
                    Lead.temperature == LeadTemperature.HOT,
                    Lead.is_active == True,
                    Lead.status.not_in([LeadStatus.WON, LeadStatus.LOST]),
                    Lead.last_contact < hot_threshold
                )
                .all()
            )
            
            # Find warm leads needing followup
            warm_leads = (
                db.query(Lead)
                .filter(
                    Lead.temperature == LeadTemperature.WARM,
                    Lead.is_active == True,
                    Lead.status.not_in([LeadStatus.WON, LeadStatus.LOST]),
                    Lead.last_contact < warm_threshold
                )
                .all()
            )
            
            # Find cold leads needing followup
            cold_leads = (
                db.query(Lead)
                .filter(
                    Lead.temperature == LeadTemperature.COLD,
                    Lead.is_active == True,
                    Lead.status.not_in([LeadStatus.WON, LeadStatus.LOST]),
                    Lead.last_contact < cold_threshold
                )
                .all()
            )
            
            return hot_leads + warm_leads + cold_leads
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def get_followup_priority(cls, lead: Lead) -> int:
        """
        Determine the priority of a follow-up based on lead temperature.
        
        Args:
            lead: The lead to follow up with
            
        Returns:
            Priority level (1-3, where 3 is highest)
        """
        if lead.temperature == LeadTemperature.HOT:
            return 3
        elif lead.temperature == LeadTemperature.WARM:
            return 2
        else:
            return 1
    
    @classmethod
    def get_followup_delay(cls, lead: Lead) -> timedelta:
        """
        Determine the delay for a follow-up based on lead temperature.
        
        Args:
            lead: The lead to follow up with
            
        Returns:
            Timedelta representing the delay
        """
        if lead.temperature == LeadTemperature.HOT:
            return timedelta(hours=6)
        elif lead.temperature == LeadTemperature.WARM:
            return timedelta(hours=24)
        else:
            return timedelta(days=3) 