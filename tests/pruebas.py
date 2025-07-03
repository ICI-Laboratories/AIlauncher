import requests
import time

# --- Configuration ---
API_URL = "http://localhost:8000/chat"
API_KEY = "changeme"
REQUEST_COUNT = 10
HEADERS = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
}

# --- Main Function ---
def main():
    """Sends multiple requests in a loop and prints the streaming response."""
    print(f"🔥 Sending {REQUEST_COUNT} requests to {API_URL}")

    for i in range(1, REQUEST_COUNT + 1):
        prompt_text = f"Hello from request #{i}. Tell me a short, interesting fact about space."
        payload = {"prompt": prompt_text}

        print(f"\n▶️  Starting request #{i}...")
        start_time = time.time()

        try:
            # Use a streaming request with a much longer timeout
            with requests.post(API_URL, headers=HEADERS, json=payload, stream=True, timeout=(5, 300)) as response:
                response.raise_for_status()

                print(f"   Response from #{i}: ", end="", flush=True)
                full_response = ""
                
                # Print each chunk as it arrives to show the streaming is working
                for chunk in response.iter_content(decode_unicode=True):
                    if chunk:
                        print(chunk, end="", flush=True)
                        full_response += chunk

                end_time = time.time()
                print(f"\n✅ Success! Request #{i} finished in {end_time - start_time:.2f}s")
                
        except requests.exceptions.RequestException as e:
            print(f"❌ An error occurred in request #{i}: {e}")
            
    print("\n🏁 All requests complete.")

# --- Run the Script ---
if __name__ == "__main__":
    main()