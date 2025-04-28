import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app.services.agent import SalesCloserAgent
from app.services.memory import MemoryManager
from app.db.models import Lead, Conversation, LeadStatus, ConversationChannel


class TestSalesCloserAgent:
    """Tests for the SalesCloserAgent class."""
    
    def setup_method(self):
        """Setup for each test method."""
        # Create a mock database session
        self.mock_db = MagicMock()
        
        # Create a test lead
        self.test_lead = Lead(
            id=1,
            first_name="John",
            last_name="Doe",
            email="john.doe@example.com",
            company="ACME Inc.",
            job_title="CTO",
            status=LeadStatus.NEW,
            preferred_channel=ConversationChannel.EMAIL,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_active=True
        )
        
        # Create some test conversations
        self.test_conversations = [
            Conversation(
                id=1,
                lead_id=1,
                channel=ConversationChannel.EMAIL,
                is_from_lead=True,
                content="I'm interested in your services.",
                created_at=datetime.utcnow() - timedelta(days=1)
            ),
            Conversation(
                id=2,
                lead_id=1,
                channel=ConversationChannel.EMAIL,
                is_from_lead=False,
                content="Great! I'd be happy to tell you more. What specific needs do you have?",
                created_at=datetime.utcnow() - timedelta(days=1, hours=23)
            )
        ]
        
        # Initialize agent with mock OpenAI API key
        self.agent = SalesCloserAgent(openai_api_key="fake-api-key")
    
    @patch('app.services.agent.openai')
    @patch('app.services.memory.MemoryManager.get_lead_by_email')
    @patch('app.services.memory.MemoryManager.add_message')
    @patch('app.services.memory.MemoryManager.get_lead_context')
    @patch('app.services.messaging.MessagingService.send_message')
    def test_handle_message(
        self, 
        mock_send_message, 
        mock_get_lead_context, 
        mock_add_message, 
        mock_get_lead_by_email,
        mock_openai
    ):
        """Test handling an incoming message from a lead."""
        # Setup mocks
        mock_get_lead_by_email.return_value = self.test_lead
        
        mock_get_lead_context.return_value = {
            "name": "John Doe",
            "email": "john.doe@example.com",
            "company": "ACME Inc.",
            "job_title": "CTO",
            "status": "new",
            "conversation_history": "No previous conversation"
        }
        
        # Mock OpenAI response
        mock_openai.ChatCompletion.create.return_value = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content="Thanks for your interest, John! What specific problems are you trying to solve?"
                    )
                )
            ]
        )
        
        # Mock message sending
        mock_send_message.return_value = {"success": True}
        
        # Call the function
        result = self.agent.handle_message(
            lead_email="john.doe@example.com",
            message_content="Tell me more about your pricing.",
            channel=ConversationChannel.EMAIL,
            db=self.mock_db
        )
        
        # Assert results
        assert result["success"] is True
        assert "response" in result
        assert "Thanks for your interest, John!" in result["response"]
        
        # Verify mocks were called
        mock_get_lead_by_email.assert_called_once_with("john.doe@example.com", self.mock_db)
        mock_add_message.assert_called()
        mock_get_lead_context.assert_called_once_with(self.test_lead.id, self.mock_db)
        mock_send_message.assert_called_once()
    
    @patch('app.services.agent.openai')
    @patch('app.services.memory.MemoryManager.get_lead_context')
    @patch('app.services.memory.MemoryManager.add_message')
    @patch('app.services.messaging.MessagingService.send_message')
    def test_greet_lead(
        self,
        mock_send_message,
        mock_add_message,
        mock_get_lead_context,
        mock_openai
    ):
        """Test sending an initial greeting to a lead."""
        # Setup mocks
        mock_get_lead_context.return_value = {
            "name": "John Doe",
            "email": "john.doe@example.com",
            "company": "ACME Inc.",
            "job_title": "CTO",
            "status": "new",
            "conversation_history": "No previous conversation"
        }
        
        # Mock OpenAI response
        mock_openai.ChatCompletion.create.return_value = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content="Hello John, I'm your AI sales assistant. How can I help your company today?"
                    )
                )
            ]
        )
        
        # Mock message sending
        mock_send_message.return_value = {"success": True}
        
        # Call the function
        result = self.agent.greet_lead(
            lead=self.test_lead,
            db=self.mock_db
        )
        
        # Assert results
        assert result["success"] is True
        assert "greeting" in result
        assert "Hello John" in result["greeting"]
        
        # Verify mocks were called
        mock_get_lead_context.assert_called_once_with(self.test_lead.id, self.mock_db)
        mock_add_message.assert_called_once()
        mock_send_message.assert_called_once()
    
    def test_parse_response_for_actions(self):
        """Test parsing actions from a response."""
        # Test response with actions
        response_with_actions = """
        Hello John, thank you for your interest in our services!
        
        [ACTION:UPDATE_LEAD|status=interested|needs=automation software]
        
        I'd be happy to schedule a quick call to discuss your needs.
        
        [ACTION:SCHEDULE_MEETING|time=2023-12-15T15:00:00|duration=30|type=discovery]
        
        Looking forward to our conversation!
        """
        
        cleaned_text, actions = self.agent._parse_response_for_actions(response_with_actions)
        
        # Assert cleaned text doesn't contain action tags
        assert "[ACTION:" not in cleaned_text
        
        # Assert actions were correctly parsed
        assert len(actions) == 2
        assert actions[0]["type"] == "UPDATE_LEAD"
        assert actions[0]["params"]["status"] == "interested"
        assert actions[1]["type"] == "SCHEDULE_MEETING"
        assert actions[1]["params"]["time"] == "2023-12-15T15:00:00"
        
        # Test response without actions
        response_without_actions = "Hello John, thank you for your interest in our services!"
        cleaned_text, actions = self.agent._parse_response_for_actions(response_without_actions)
        
        # Assert nothing changed in text
        assert cleaned_text == response_without_actions
        
        # Assert no actions were found
        assert len(actions) == 0 