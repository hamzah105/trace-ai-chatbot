import os

import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300"))


class OllamaServiceError(Exception):
    pass


class OllamaTimeoutError(OllamaServiceError):
    pass


def generate_response(prompt: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 140
        }
    }

    if os.getenv("TRACE_OOMP_MODE", "off") != "off":
        from backend.services.oomp_config import get_configuration
        payload["options"]["num_ctx"] = get_configuration().num_ctx

    try:
        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=(5, OLLAMA_TIMEOUT_SECONDS),
        )
        response.raise_for_status()
        data = response.json()
    except requests.Timeout as error:
        raise OllamaTimeoutError(
            f"LLaMA 3 did not respond within {OLLAMA_TIMEOUT_SECONDS:g} seconds"
        ) from error
    except requests.RequestException as error:
        raise OllamaServiceError("Could not connect to the local Ollama service") from error
    except ValueError as error:
        raise OllamaServiceError("Ollama returned an invalid response") from error

    generated_text = data.get("response", "").strip()
    if not generated_text:
        raise OllamaServiceError("LLaMA 3 returned an empty response")
    return generated_text
