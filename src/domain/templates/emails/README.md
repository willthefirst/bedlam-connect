# Domain templates: transactional emails

Templates rendered as email bodies, not HTTP responses. Each pair is
`<name>.html` + `<name>.txt` — both parts required for deliverability
(text/plain keeps the spam score down at strict providers).

## Grammar (deviates from `src/domain/templates/`)

These templates **do not extend** `base.html`. Each file is fully
self-contained — inline CSS only, no JS, no `{% include %}`. Email clients
(especially Gmail / Outlook) strip `<head>`-level styles and reject anything
that smells like a web page, so the chrome-portable patterns the rest of the
templates use don't apply here.

**One shared import is allowed:** the support footer. Both parts of every
pair import it — the HTML part pulls `support_note_html` from
[`_shared/support.html`](../../../framework/templates/_shared/support.html),
the text part pulls `support_note_text` from
[`_shared/support.txt`](../../../framework/templates/_shared/support.txt).
Those macros are the single home for the "reach us" line, the support
address, and the pre-filled `mailto:`, shared with the site `<footer>` so
the copy never drifts between the site and the mail we send. They emit only
inline-safe content (the text macro emits no HTML at all), so the
self-contained-output rule still holds. Any *other* shared partial stays
out — this is the one carve-out.

The Jinja env that renders these is the same one used for HTTP
responses (`src.framework.rendering.templating.templates.env`); the
`.html` autoescape rule still applies, so user-supplied values like
`{{ username }}` are HTML-safe in the HTML part. `.txt` files do not
autoescape (extension-based), so the plain-text part should never
embed untrusted attribute-shaped content.

## Where these are rendered

Domain wrappers in `src/domain/logic/<entity>/emails.py` render both
parts of a pair, then hand off to the framework's `send_email`. Callers
(fastapi-users hooks in `src.auth_config.UserManager`, route handlers)
call those wrappers — never `_render` or `send_email` directly.

## Links must be absolute

Every link a template renders comes from the framework's `absolute_url`
(see [`src/framework/email/README.md`](../../../framework/email/README.md))
— never a hand-written `href="/..."`. [`test_links.py`](test_links.py)
renders every template here through its real wrapper and fails on any
non-absolute link, and a new template without a case there fails too.
