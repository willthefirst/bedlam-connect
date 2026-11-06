# Privacy defaults

What is captured once `storyteller.start()` is called:
- DOM structure and visible text of pages the visitor sees, and changes to it
- clicks, focus, scroll position, mouse position (sampled), tab visibility, URL changes, JS errors
- an anonymous visitor id (localStorage) and, if your site calls `identify()`, your user id and any facts you pass

What is never captured:
- the contents of any input or textarea (always masked; only character counts are recorded)
- anything inside an element marked `data-no-record`
- all text, if `maskAllText: true` is set in `init()`

Controls:
- Nothing records until the site calls `start()`. Obtain whatever consent your jurisdiction requires first.
- `storyteller.stop()` stops this visit; `storyteller.optOut()` stops this browser permanently; the Global Privacy Control header is honored as an opt-out.
- `POST /storyteller/recording {"enabled": false}` stops all recording everywhere within five minutes.

Where data goes:
- raw events: the service's buffer on disk, deleted once the story is written (or moved to `failed/` on error)
- the timeline and story: your app, through the write hook, plus your LLM provider (the timeline text, not raw events) under your own account and terms. Use a local model to keep everything in-house.

Each story carries a `consent` record so you can show how recording was authorized.
