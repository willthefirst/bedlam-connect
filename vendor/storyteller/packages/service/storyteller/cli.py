"""
storyteller timeline <recording.json>            print the readable timeline
storyteller story <recording.json> [--brief f] [--history f] [--config f] [--out f]
storyteller schema                                print the Story JSON schema
storyteller serve [--config f]                    run the service
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .timeline import build_timeline


def _load_rec(path: str) -> dict:
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):  # bare rrweb event array (e.g. from rrweb's own tooling)
        data = {"visitorId": "unknown", "visitId": Path(path).stem, "events": data}
    return data


def cmd_timeline(a: argparse.Namespace) -> int:
    tl = build_timeline(_load_rec(a.recording))
    if a.json:
        print(json.dumps(tl.to_dict(), indent=2))
    else:
        d = tl.device or {}
        print(f"visit {tl.visit_id}  visitor {tl.visitor_id}  user {tl.user_id or '-'}")
        print(f"{tl.started_at.isoformat(timespec='seconds')}  {tl.duration_s}s  {'mobile' if d.get('mobile') else 'desktop'} {d.get('browser','?')}  pages: {' → '.join(tl.pages)}")
        print()
        print(tl.render())
    return 0


def cmd_story(a: argparse.Namespace) -> int:
    from .config import load_config
    from .llm import load_brain
    from .story import tell_story

    cfg = load_config(a.config)
    brief = Path(a.brief).read_text() if a.brief else cfg.brief_text()
    history = json.load(open(a.history)) if a.history else None
    brain = load_brain(cfg.llm)
    tl = build_timeline(_load_rec(a.recording))
    story = tell_story(tl, brain, brief, history)
    out = story.model_dump_json(indent=2)
    if a.out:
        Path(a.out).write_text(out)
        print(f"wrote {a.out}", file=sys.stderr)
    if not a.out or a.print:
        print(out)
    if not a.quiet:
        print("\n--- narrative ---\n" + story.narrative, file=sys.stderr)
        print(f"outcome: {story.outcome.label} ({story.outcome.confidence:.2f})  tags: {', '.join(story.tags)}", file=sys.stderr)
        for f in story.friction:
            print(f"  friction @t={f.at:.0f}s ({f.confidence:.2f}): {f.inference}", file=sys.stderr)
        p = story.provenance
        print(f"model {p.model}  tokens in/out {p.input_tokens}/{p.output_tokens}  attempts {p.attempts}", file=sys.stderr)
    return 0


def cmd_schema(a: argparse.Namespace) -> int:
    from .story.schema import export_full_schema

    print(json.dumps(export_full_schema(), indent=2))
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app
    from .config import load_config

    cfg = load_config(a.config)
    uvicorn.run(create_app(cfg), host=a.host, port=a.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="storyteller", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("timeline")
    t.add_argument("recording")
    t.add_argument("--json", action="store_true")
    t.set_defaults(fn=cmd_timeline)
    s = sub.add_parser("story")
    s.add_argument("recording")
    s.add_argument("--brief")
    s.add_argument("--history")
    s.add_argument("--config")
    s.add_argument("--out")
    s.add_argument("--print", action="store_true")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(fn=cmd_story)
    sc = sub.add_parser("schema")
    sc.set_defaults(fn=cmd_schema)
    sv = sub.add_parser("serve")
    sv.add_argument("--config")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8787)
    sv.set_defaults(fn=cmd_serve)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
