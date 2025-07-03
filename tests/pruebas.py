import requests
import sys

# --- Configuration ---
API_URL = "http://localhost:8000/chat"
API_KEY = "changeme"
HEADERS = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
}

def chat_session():
    """Starts an interactive chat session with configurable parameters."""
    print("🤖 AI Chat Client")
    print("=" * 20)

    # --- Set parameters for the session ---
    try:
        system_prompt = input("Enter system prompt (e.g., 'You are a pirate'): ")
        temp_str = input("Enter temperature (e.g., 0.8): ")
        temperature = float(temp_str)
    except (ValueError, TypeError):
        print("Invalid input. Using default parameters.")
        system_prompt = "You are a helpful assistant."
        temperature = 0.8
        
    print("\n✅ Session configured. Type 'exit' or press Ctrl+C to quit.\n")

    while True:
        try:
            prompt = input("You: ")
            if prompt.lower().strip() == 'exit':
                print("\n👋 Exiting chat session.")
                break

            # --- Build the request payload with new parameters ---
            payload = {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": 1024, # Increased max tokens for longer stories
            }

            with requests.post(API_URL, headers=HEADERS, json=payload, stream=True, timeout=300) as response:
                response.raise_for_status()
                
                print("AI:  ", end="", flush=True)
                for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                    if chunk:
                        print(chunk, end="", flush=True)
                print("\n")

        except requests.exceptions.RequestException as e:
            print(f"\n❌ Connection Error: {e}")
            break
        except (KeyboardInterrupt, EOFError):
            print("\n👋 Exiting chat session.")
            break

if __name__ == "__main__":
    chat_session()