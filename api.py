import requests
import json

def test_chatbot_simple():
    url = "http://localhost:8000/query/"
    
    print("Book Chatbot Test Interface")
    print("Type 'exit' to quit the chat\n")
    
    while True:
        # Get user input
        question = input("You: ")
        if question.lower() == 'exit':
            print("\nGoodbye!")
            break
            
        try:
            # Make the request
            response = requests.post(
                url,
                json={"query": question},
                headers={"Content-Type": "application/json"}
            )
            
            # Process the response
            if response.status_code == 200:
                result = response.json()
                if result["status"] == "success":
                    print("\nAssistant:", result["response"], "\n")
                else:
                    print("\nError:", result["error"], "\n")
            else:
                print(f"\nError: Failed to get response (Status code: {response.status_code})\n")
                
        except Exception as e:
            print(f"\nError: {str(e)}\n")

if __name__ == "__main__":
    test_chatbot_simple()