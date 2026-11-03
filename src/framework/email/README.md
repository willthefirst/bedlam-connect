# Framework: email transport

One async function (`send_email`) dispatched to one of three backends
behind it. Callers don't know the provider.

## Backend dispatch

`settings.EMAIL_BACKEND` selects the transport at call time:

- `console` (default) — prints subject + recipient + plain-text body to
  stderr. Used in dev so verify/reset links land in the terminal,
  clickable, with zero external dependencies.
- `file` — writes a timestamped `.eml`-shaped file under `./.mail/`
  (gitignored). Useful when you want to inspect the HTML version of
  the email a render produced.
- `resend` — calls the Resend HTTP API. Production. Requires
  `RESEND_API_KEY` to be set and `EMAIL_FROM` to live on a
  DKIM/SPF-verified domain.

The `console` default means a fresh checkout never sends real mail by
accident — flipping to `resend` requires both an env-var change and a
valid API key.

## Public surface

```python
from src.framework.email import send_email

await send_email(
    to="user@example.com",
    subject="Verify your email",
    html="<p>…</p>",
    text="…",
    reply_to=None,  # optional; see below
)
```

Both `html` and `text` parts are required — text/plain is what keeps
the spam score down at deliverability-strict providers. Callers
render both from the same template pair (see
`src/domain/templates/emails/`).

Every link in an email body is built with `absolute_url(path)` (in
[`links.py`](links.py)), which joins `settings.APP_BASE_URL` with an app
path. Email clients have no page to resolve a relative `href` against —
Gmail silently repairs a scheme-less one, other clients resolve it
against their own domain and 404 — so `APP_BASE_URL` is validated at
boot in [`config.py`](../config.py) (scheme required) and every rendered
link is pinned absolute by
[`templates/emails/test_links.py`](../../domain/templates/emails/test_links.py).

`reply_to` is the optional address a recipient's "Reply" goes to
when it differs from the sending `EMAIL_FROM` address (e.g. an
in-app message-the-poster flow where the conversation should
continue between the two real users, not loop back to a no-reply
mailbox). Omit it (the default `None`) when replies should bounce
or land in `EMAIL_FROM`'s inbox — the Resend payload simply won't
carry the key.

## Why provider-shaped

`send_email` is the only public function. Backends live behind it.
Swapping Resend for Postmark / SES / anything else is a single
`_send_resend` rewrite in [`sender.py`](sender.py), not a
touch-every-caller refactor. This is why callers never `import resend`
directly.

## Errors

Errors propagate. fastapi-users hooks (the primary callers) don't
expose a retry surface — and adding one would be the wrong layer. If a
provider call fails, the user sees a generic error; they can
re-request the email via the standard re-send route.
