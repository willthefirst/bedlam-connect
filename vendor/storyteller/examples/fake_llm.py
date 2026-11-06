"""
An OpenAI-compatible fake LLM for local end-to-end testing with no API key.
Returns a plausible story that quotes the timeline it was given.
Run:  uvicorn examples.fake_llm:app --port 8010
Config: llm.provider=openai_compatible, llm.base_url=http://localhost:8010/v1
"""
import json
import re

from fastapi import FastAPI, Request

app = FastAPI(title="Fake LLM")


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    user = next((m["content"] for m in body["messages"] if m["role"] == "user"), "")
    if isinstance(user, list):
        user = " ".join(p.get("text", "") for p in user if p.get("type") == "text")
    tl = re.search(r"<timeline>(.*?)</timeline>", user, re.S)
    lines = [l for l in (tl.group(1) if tl else "").splitlines() if l.strip().startswith("t=")]
    errors = [l for l in lines if "error shown" in l]
    rage = [l for l in lines if "rage click" in l]
    pages = re.search(r"pages: (.*)", user)
    label = "abandoned_signup" if errors else ("completed_signup" if any("dialog opened" in l for l in lines) else ("bounced" if len(lines) <= 3 else "browsed"))
    friction = []
    for l in errors[:1] + rage[:1] + [l for l in lines if "no input" in l][:1]:
        t = float(re.search(r"t=(\d+)", l).group(1))
        friction.append({"at": t, "evidence": l.strip(), "inference": "fake inference about this moment", "confidence": 0.6})
    story = {
        "narrative": f"(fake LLM) The visitor went {pages.group(1) if pages else 'nowhere'} over {len(lines)} timeline lines. " + (f"They hit an error: {errors[0].strip()}. " if errors else "") + (f"They rage-clicked: {rage[0].strip()}." if rage else ""),
        "outcome": {"label": label, "observed": lines[-1].strip() if lines else "", "inferred": "fake", "confidence": 0.5},
        "tags": ["fake", label],
        "friction": friction,
        "observations": [l.strip() for l in lines[:3]],
        "visitor_summary": "Fake summary: " + ("returning visitor" if "prior visits" in user else "first visit"),
        "suggestions": [],
    }
    return {"id": "fake", "model": "fake-llm", "choices": [{"message": {"role": "assistant", "content": json.dumps(story)}}], "usage": {"prompt_tokens": len(user) // 4, "completion_tokens": 200}}
