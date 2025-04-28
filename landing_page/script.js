// DOM Elements
const chatMessages = document.getElementById('chat-messages');
const userMessageInput = document.getElementById('user-message');
const sendMessageButton = document.getElementById('send-message');
const leadForm = document.getElementById('lead-form');

// API URL - replace with your actual API endpoint when deployed
const API_URL = '/api/v1/chat';

// Store lead information
let currentLead = {
    email: null,
    name: null,
    company: null
};

// Chat functionality
document.addEventListener('DOMContentLoaded', function() {
    // Scroll chat to bottom
    scrollToBottom();

    // Add event listeners
    sendMessageButton.addEventListener('click', sendMessage);
    userMessageInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });

    if (leadForm) {
        leadForm.addEventListener('submit', handleLeadForm);
    }
});

function sendMessage() {
    const message = userMessageInput.value.trim();
    
    if (message === '') return;
    
    // Add user message to chat
    addMessageToChat(message, 'user');
    
    // Clear input
    userMessageInput.value = '';
    
    // Request response from AI
    if (currentLead.email) {
        requestAIResponse(message);
    } else {
        // If no lead info, show a message asking to fill the form
        setTimeout(() => {
            const response = "Please fill out the contact form below to create an account before we continue our conversation.";
            addMessageToChat(response, 'agent');
            scrollToBottom();
        }, 1000);
    }
}

function addMessageToChat(message, sender) {
    const messageElement = document.createElement('div');
    messageElement.classList.add('message', sender);
    
    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    
    messageElement.innerHTML = `
        <div class="message-content">
            <p>${message}</p>
        </div>
        <div class="message-time">${timestamp}</div>
    `;
    
    chatMessages.appendChild(messageElement);
    scrollToBottom();
}

function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function requestAIResponse(message) {
    try {
        // Show typing indicator
        const typingIndicator = document.createElement('div');
        typingIndicator.classList.add('message', 'agent', 'typing-indicator');
        typingIndicator.innerHTML = `
            <div class="message-content">
                <p>Typing<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span></p>
            </div>
        `;
        chatMessages.appendChild(typingIndicator);
        scrollToBottom();
        
        // In a real implementation, this would be a fetch call to your backend
        // For demonstration, we'll simulate a response
        
        let response;
        
        // Check for compliance issues (simple client-side check for demo)
        if (message.toLowerCase().includes('illegal') || 
            message.toLowerCase().includes('fraud') || 
            message.toLowerCase().includes('hack')) {
            response = "I apologize, but I cannot assist with topics that may violate legal or ethical standards. I'll connect you with a human representative who can better assist you with your inquiry. They will contact you shortly.";
        } else {
            // Simulate API call with setTimeout
            await new Promise(resolve => setTimeout(resolve, 2000));
            
            // Simulate different responses based on message content
            if (message.toLowerCase().includes('pricing') || message.toLowerCase().includes('cost')) {
                response = "Our pricing is based on your specific needs and conversation volume. The Starter plan begins at $99/month for up to 100 conversations. Would you like me to tell you more about our pricing options or would you prefer to discuss something else?";
            } 
            else if (message.toLowerCase().includes('demo') || message.toLowerCase().includes('try')) {
                response = "I'd be happy to set up a personalized demo for you! To get started, could you tell me a bit more about your business needs and what you're looking to accomplish with our AI Sales Closer?";
            }
            else if (message.toLowerCase().includes('compliance') || message.toLowerCase().includes('guardrails')) {
                response = "Our compliance guardrails system automatically detects potentially risky conversations about illegal activities, privacy violations, financial fraud, and other concerning topics. When detected, these conversations are immediately escalated to human review while providing a professional response to the lead. Would you like to know more about our compliance features?";
            }
            else {
                response = "Thank you for your message! Our AI Sales Closer can help you convert more leads while ensuring compliance with regulations. Would you like to know more about specific features or how it could benefit your business?";
            }
        }
        
        // Remove typing indicator
        chatMessages.removeChild(typingIndicator);
        
        // Add AI response
        addMessageToChat(response, 'agent');
        
    } catch (error) {
        console.error('Error getting AI response:', error);
        
        // Remove typing indicator if it exists
        const indicator = document.querySelector('.typing-indicator');
        if (indicator) {
            chatMessages.removeChild(indicator);
        }
        
        // Show error message
        addMessageToChat("I'm sorry, there was an error processing your request. Please try again later.", 'agent');
    }
}

function handleLeadForm(e) {
    e.preventDefault();
    
    // Get form data
    const name = document.getElementById('name').value;
    const email = document.getElementById('email').value;
    const company = document.getElementById('company').value;
    const message = document.getElementById('message').value;
    
    // Store lead info
    currentLead = {
        name,
        email,
        company
    };
    
    // In a real implementation, you would send this data to your backend
    // For now, we'll just simulate a successful submission
    
    // Clear form
    e.target.reset();
    
    // Show success message
    const successMessage = document.createElement('div');
    successMessage.classList.add('form-success');
    successMessage.textContent = 'Thank you for your interest! We\'ll be in touch soon.';
    
    // Insert after form
    e.target.parentNode.insertBefore(successMessage, e.target.nextSibling);
    
    // Remove success message after 5 seconds
    setTimeout(() => {
        successMessage.remove();
    }, 5000);
    
    // Add welcome message in chat
    setTimeout(() => {
        const welcomeMessage = `Hi ${name}! Thanks for your interest in AI Sales Closer. How can I help you today?`;
        addMessageToChat(welcomeMessage, 'agent');
    }, 1000);
    
    // Scroll to chat section
    document.getElementById('demo').scrollIntoView({ behavior: 'smooth' });
}

// Add animations for typing indicator
setInterval(() => {
    const dots = document.querySelectorAll('.typing-indicator .dot');
    dots.forEach((dot, index) => {
        setTimeout(() => {
            dot.style.opacity = '1';
            setTimeout(() => {
                dot.style.opacity = '0.3';
            }, 300);
        }, index * 150);
    });
}, 1000);

// In a real implementation, you would integrate with your backend API
// For example:
/*
async function requestAIResponse(message) {
    try {
        // Show typing indicator
        const typingIndicator = document.createElement('div');
        typingIndicator.classList.add('message', 'agent', 'typing-indicator');
        typingIndicator.innerHTML = `
            <div class="message-content">
                <p>Typing<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span></p>
            </div>
        `;
        chatMessages.appendChild(typingIndicator);
        scrollToBottom();
        
        // Make API request
        const response = await fetch(API_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                message: message,
                lead_email: currentLead.email,
                channel: 'WEBCHAT'
            }),
        });
        
        const data = await response.json();
        
        // Remove typing indicator
        chatMessages.removeChild(typingIndicator);
        
        // Add AI response
        if (data.success) {
            addMessageToChat(data.response, 'agent');
        } else {
            addMessageToChat("I'm sorry, there was an error processing your request. Please try again later.", 'agent');
        }
        
    } catch (error) {
        console.error('Error getting AI response:', error);
        
        // Remove typing indicator if it exists
        const indicator = document.querySelector('.typing-indicator');
        if (indicator) {
            chatMessages.removeChild(indicator);
        }
        
        // Show error message
        addMessageToChat("I'm sorry, there was an error processing your request. Please try again later.", 'agent');
    }
}
*/ 