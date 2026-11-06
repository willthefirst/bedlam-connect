"""
A minimal consumer app: what your FastAPI app needs to add.
Run:  STORYTELLER_SECRET=dev uvicorn examples.demo_consumer:app --port 8000
Then open http://localhost:8000/internal/storyteller/ui
"""
import sys
from pathlib import Path

from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "adapters" / "fastapi"))
from storyteller_adapter import make_router  # noqa: E402

app = FastAPI(title="Demo consumer")
app.include_router(make_router(db_path=str(Path(__file__).resolve().parent / "demo_consumer.db")))


@app.get("/")
def home():
    return {"hello": "this is your app", "stories_ui": "/internal/storyteller/ui"}
