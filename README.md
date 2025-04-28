# AI Sales Closer

An intelligent sales agent powered by AI that handles conversations with leads, recommends products, and closes deals - all with built-in compliance protection.

## Overview

The AI Sales Closer combines GPT-4 with specialized sales strategies to create an autonomous sales agent that can:

- Engage with leads via email, SMS, or chat
- Analyze sentiment and adjust tone accordingly
- Handle objections effectively
- Schedule meetings and follow-ups
- Prioritize conversations based on lead temperature and buying signals
- Generate comprehensive sales activity reports

## Key Features

- Natural, conversational lead interaction
- Built-in compliance guardrails for risk detection
- Sentiment analysis for personalized responses
- Automated follow-ups and meeting scheduling
- Product recommendations based on lead's needs
- Detailed reporting and analytics

## Architecture

The system is built with a modular design:

- `SalesCloserAgent`: Core agent that processes messages and generates responses
- `MemoryManager`: Maintains conversation history and lead context
- `MessagingService`: Handles communication via different channels
- `SchedulerService`: Manages follow-ups and scheduled actions
- `SentimentAnalyzer`: Analyzes message sentiment and adjusts response tone
- `MessageQueue`: Prioritizes and manages incoming messages
- `PlaybookManager`: Applies conversation templates based on lead attributes
- `ReportGenerator`: Creates activity reports and insights
- `ComplianceGuardrails`: Monitors conversations for risk and regulatory compliance

## Getting Started

### Prerequisites

- Python 3.8+
- Node.js 16+ (for frontend development)
- OpenAI API key

### Installation

1. Clone the repository:

```bash
git clone https://github.com/yourusername/ai-sales-closer.git
cd ai-sales-closer
```

2. Create a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install the required dependencies:

```bash
pip install -r requirements.txt
```

4. Set up your environment variables by copying the example file:

```bash
cp env.example .env
```

5. Edit the `.env` file and add your OpenAI API key:

```
OPENAI_API_KEY=your-api-key-here
```

### Running the API

Start the FastAPI server:

```bash
python run.py
```

The API will be available at http://localhost:8000.

### Running the Landing Page

The landing page is a static website that can be opened directly in a browser:

1. Navigate to the project directory
2. Open `index.html` in your browser

For a more production-like environment, you can use a simple HTTP server:

```bash
python -m http.server 8080
```

Then access the landing page at http://localhost:8080.

## API Endpoints

### Chat with Agent

```
POST /api/v1/chat
```

Request body:
```json
{
  "message": "I'm interested in your product",
  "lead_email": "customer@example.com",
  "channel": "WEBCHAT"
}
```

Response:
```json
{
  "success": true,
  "response": "Thank you for your interest! What aspects of our product would you like to know more about?",
  "lead_id": 123,
  "actions": []
}
```

### Create Lead

```
POST /api/v1/leads
```

Request body:
```json
{
  "email": "customer@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "company": "ACME Inc",
  "job_title": "CEO",
  "source": "Website"
}
```

Response:
```json
{
  "success": true,
  "message": "Lead created successfully",
  "lead_id": 123
}
```

## Integration with Web Interface

To connect the landing page with your AI Sales Closer API:

1. Edit the `script.js` file in the landing page directory
2. Update the `API_URL` constant with your API endpoint
3. Uncomment the `requestAIResponse` function that makes an actual API call

```javascript
// In script.js
const API_URL = 'http://your-server-url:8000/api/v1/chat';
```

## Usage Examples

### Basic Agent Usage

```python
from app.services.agent import SalesCloserAgent

# Initialize the agent
agent = SalesCloserAgent(openai_api_key="your-api-key")

# Process a message from a lead
result = agent.handle_message(
    lead_email="customer@example.com",
    message_content="I'm interested in your product. What's the pricing?",
    channel="email"
)

# Generate reports
report = agent.generate_daily_report(recipient_email="admin@yourcompany.com")
```

### Testing

You can test the AI agent functionality using the provided test scripts:

```bash
python simple_agent_test.py  # Tests basic agent functionality and compliance
python test_agent.py         # Tests more comprehensive agent features
```

## Compliance Guardrails

The AI Sales Closer includes built-in compliance guardrails that detect:

- Illegal activities
- Privacy violations
- Financial fraud
- Discrimination or harassment
- Inappropriate content

When risky content is detected, the conversation is automatically escalated to a human representative and logged for review.

## Deployment

For production deployment, we recommend:

1. Deploying the API using a production ASGI server like Uvicorn behind Nginx
2. Setting up proper SSL/TLS for secure connections
3. Restricting CORS settings to specific origins
4. Hosting the landing page on a CDN or static hosting service

## License

© 2025 AI Sales Closer. All rights reserved. 