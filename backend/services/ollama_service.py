import requests

OLLAMA_URL = "http://localhost:11434/api/generate"


def generate_response(prompt: str):
    payload = {
        "model": "llama3",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.4,
            "num_predict": 180
        }
    }

    try:
        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=300
        )

        data = response.json()

        return data.get("response", "")

    except Exception as e:
        return f"Error: {str(e)}"