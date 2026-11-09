"""
ShopBot: a customer-support chatbot on a local Ollama model.

The system prompt lives in prompts/system_prompt.txt, so any change to it
is a code change that goes through CI and the eval gate.

Run the API locally:
    uvicorn app.shopbot:app --port 8000
"""

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
BOT_MODEL = os.environ.get("BOT_MODEL", "llama3.2:3b")
PROMPT_FILE = Path(os.environ.get("PROMPT_FILE", ROOT / "prompts" / "system_prompt.txt"))

# temperature 0 keeps answers (nearly) repeatable, so a failing eval
# points at a real change, not at randomness.
TEMPERATURE = 0
TIMEOUT_SECONDS = 300


def load_prompt() -> str:
    text = PROMPT_FILE.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"System prompt file is empty: {PROMPT_FILE}")
    return text


def ask(message: str) -> str:
    """Send one user message to ShopBot and return its reply."""
    r = httpx.post(
        OLLAMA_URL,
        json={
            "model": BOT_MODEL,
            "stream": False,
            "options": {"temperature": TEMPERATURE},
            "messages": [
                {"role": "system", "content": load_prompt()},
                {"role": "user", "content": message},
            ],
        },
        timeout=TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    return r.json()["message"]["content"]


app = FastAPI(title="ShopBot")


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str


@app.get("/health")
def health():
    return {"status": "ok", "model": BOT_MODEL, "prompt_file": PROMPT_FILE.name}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        return ChatResponse(response=ask(req.message))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Ollama call failed: {e}")
