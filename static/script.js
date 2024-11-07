document.addEventListener('DOMContentLoaded', function() {
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const chatMessages = document.getElementById('chat-messages');
    
    // Use the deployed URL
    const API_URL = 'https://seashell-app-794qt.ondigitalocean.app';

    function addMessage(message, isUser = false) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${isUser ? 'user-message' : 'bot-message'}`;
        
        const messageContent = document.createElement('div');
        messageContent.className = 'message-content';
        messageContent.textContent = message;
        
        messageDiv.appendChild(messageContent);
        chatMessages.appendChild(messageDiv);
        
        // Scroll to bottom
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function addTypingIndicator() {
        const typingDiv = document.createElement('div');
        typingDiv.className = 'message bot-message typing-indicator-container';
        typingDiv.innerHTML = `
            <div class="typing-indicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        `;
        chatMessages.appendChild(typingDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return typingDiv;
    }

    async function sendMessage(message) {
        try {
            const typingIndicator = addTypingIndicator();
            
            // Using the deployed URL for the API endpoint
            const response = await fetch(`${API_URL}/query/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': API_URL
                },
                body: JSON.stringify({ query: message })
            });

            typingIndicator.remove();

            if (!response.ok) {
                console.error('Server Error:', response.status, response.statusText);
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            
            if (data.status === 'success') {
                addMessage(data.response);
            } else {
                console.error('API Error:', data.error || 'Unknown error');
                addMessage('Sorry, I encountered an error while processing your request.');
            }

        } catch (error) {
            console.error('Request Error:', error);
            typingIndicator?.remove();
            addMessage('Sorry, I encountered an error while processing your request. Please try again.');
        }
    }

    chatForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const message = userInput.value.trim();
        if (message) {
            addMessage(message, true);
            userInput.value = '';
            sendMessage(message);
        }
    });

    // Add enter key support
    userInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit'));
        }
    });

    // Initial greeting
    addMessage('Hello! I am your book assistant. How can I help you today?');

    // Error handling for network issues
    window.addEventListener('online', function() {
        addMessage('Connection restored. You can continue chatting.');
    });

    window.addEventListener('offline', function() {
        addMessage('Connection lost. Please check your internet connection.');
    });

    // Prevent form submission while offline
    chatForm.addEventListener('submit', function(e) {
        if (!navigator.onLine) {
            e.preventDefault();
            addMessage('You are currently offline. Please check your internet connection.');
            return false;
        }
    });

    // Handle page visibility changes
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            // Refresh connection when page becomes visible
            if (navigator.onLine) {
                console.log('Page is visible and online');
            }
        }
    });

    // Optional: Add a function to clear chat history
    function clearChat() {
        while (chatMessages.firstChild) {
            chatMessages.removeChild(chatMessages.firstChild);
        }
        addMessage('Chat history cleared. How can I help you?');
    }

    // Optional: Add a button to clear chat
    // Uncomment if you want to add a clear chat button
    
    const clearButton = document.createElement('button');
    clearButton.textContent = 'Clear Chat';
    clearButton.className = 'clear-chat-btn';
    clearButton.onclick = clearChat;
    document.querySelector('.chat-header').appendChild(clearButton);
    
});