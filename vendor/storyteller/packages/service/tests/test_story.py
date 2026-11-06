import json
from pathlib import Path

from storyteller.llm.base import Completion, Message
from storyteller.story import tell_story
from storyteller.story.prompt import parse_brief
from storyteller.timeline import build_timeline

FIX = Path(__file__).resolve().parents[3] / "fixtures"
BRIEF = (Path(__file__).resolve().parents[3] / "examples" / "brief.example.md").read_text()


class FakeBrain:
    name = "fake"
    model = "fake-1"
    supports_images = False

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, messages, images=None, *, json=True):
        self.calls.append((system, messages))
        return Completion(text=self.replies.pop(0), model=self.model, input_tokens=10, output_tokens=5)


GOOD = json.dumps({
    "narrative": "They came from Google, compared Pro and Team, and stalled on Company name.",
    "outcome": {"label": "abandoned_signup", "observed": "left on /signup with validation error visible", "inferred": "blocked by required company name", "confidence": 0.7},
    "tags": ["signup", "form_abandon"],
    "friction": [{"at": 33, "evidence": "t=33s still on Company name, no input (9s)", "inference": "unsure what to enter", "confidence": 0.6}],
    "observations": ["compared plans for 16s"],
    "visitor_summary": "First visit; price-sensitive solo user.",
    "suggestions": [{"text": "Make company name optional", "confidence": 0.5}],
})


def test_parse_brief_sections():
    body, tags, ins = parse_brief(BRIEF)
    assert "Acme is a SaaS tool" in body
    assert "signup" in tags and "completed_signup" in tags
    assert "Keep narratives short" in ins
    assert "## Tags" not in body


def test_story_happy_path():
    tl = build_timeline(json.load(open(FIX / "compare_abandon.json")))
    brain = FakeBrain([GOOD])
    story = tell_story(tl, brain, BRIEF, history=None)
    assert story.outcome.label == "abandoned_signup"
    assert story.history_available is False
    assert story.trajectory[-1].visit_id == tl.visit_id
    assert story.provenance.attempts == 1
    system, msgs = brain.calls[0]
    assert "Never invent events" in system
    assert "Company name is required" in msgs[0].content  # timeline made it into the prompt
    assert "Keep narratives short" in msgs[0].content  # instructions from brief
    assert "No prior visits" in msgs[0].content


def test_story_retries_then_falls_back():
    tl = build_timeline(json.load(open(FIX / "bounce.json")))
    brain = FakeBrain(["not json at all", '{"narrative": "x"}'])
    story = tell_story(tl, brain, BRIEF)
    assert story.outcome.label == "generation_failed"
    assert story.provenance.attempts == 2
    assert story.timeline_text  # consumer still gets the timeline


def test_history_flows_into_prompt_and_trajectory():
    tl = build_timeline(json.load(open(FIX / "success_rage.json")))
    history = {
        "summary": "Second visit.",
        "trajectory": [{"visit_id": "v0", "started_at": "2026-11-01T10:00:00", "outcome": "abandoned_signup", "friction": ["company name"]}],
        "facts": [{"text": "This is my friend Sam", "weight": "high"}],
        "instructions": {"global": "Be skeptical about idle time.", "visitor": "Sam is an expert."},
    }
    brain = FakeBrain([GOOD])
    story = tell_story(tl, brain, BRIEF, history=history)
    assert story.history_available
    assert [t.visit_id for t in story.trajectory] == ["v0", tl.visit_id]
    content = brain.calls[0][1][0].content
    assert "my friend Sam" in content and "weight=high" in content
    assert "Sam is an expert" in content and "skeptical" in content
