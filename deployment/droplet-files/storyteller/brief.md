# Site brief: Bedlam Connect

Bedlam Connect is a referral and clinician-opening directory for the U.S. mental health workforce. Clinicians, program staff and other members post and browse three kinds of posts: **referrals** (a clinician looking for someone to take a client), **clinician openings** (a clinician with availability) and **program intakes** (a program accepting clients). The point of a visit is to find a match and start a conversation about it.

## Pages

- `/` — public landing page for anonymous visitors; signed-in members are redirected to `/posts`.
- `/auth/register`, `/auth/login`, `/auth/forgot-password` — account flow. New accounts must verify their email, and clinicians verify their license via NPI lookup before they can post.
- `/posts` — the main board: every post kind in one feed with a sidebar filter (kind, state, services, insurance, age group, language, format, etc.). Members can save a filter set as a saved search.
- `/posts/{id}` — a post's detail page. The key action is the **Message** form, which emails the post's owner and creates a connection between the two members.
- `/posts/form` — create a post: a kind picker first, then the kind's form (the referral form is long and sectioned).
- `/clinicians`, `/organizations`, `/programs` — supporting directories, reachable by URL rather than from the nav.
- `/users/me` — the member's own profile, with a "Getting started" checklist of what they still need to do before they can post.
- `/admin/*`, `/internal/*` — staff tooling; ignore for stories.

## Who uses it

Working clinicians (therapists, psychiatrists, social workers), intake coordinators at programs, and the people who run small practices. Many are on a phone between sessions. Most arrive from a direct link or a colleague's recommendation, not from search.

## What a successful visit looks like

- A member browses `/posts`, opens one or more posts, and sends a message from a post's detail page.
- A member creates a post and reaches the post's detail page afterwards.
- A new visitor registers, verifies their email, and completes the "Getting started" steps.
- For a quick return visit, checking the board and leaving within a minute can be fine — look at whether they found what they came for.

## Known trouble spots

- Posting is gated: unverified accounts see locked "Post" affordances. Clicking a locked affordance opens a small popover explaining why. People stalling here are blocked by verification, not confused by the form.
- The referral form is long; partial fills and back-and-forth between sections are expected, abandonment after an error is not.
- The sidebar filter applies on an explicit "Apply" click; people sometimes change filters and wait for the list to update on its own.
- Email verification links open in a new tab, so a visit can show a long idle gap and then resume.

## Recent changes

- (keep this list current: date — what changed, so stories can tell "new" from "broken")

## Tags
registered, verified_email, verified_license, browsed_board, filtered, saved_search, opened_post, sent_message, created_post, abandoned_post_form, locked_out_unverified, validation_error, bounce, returning, mobile, bug

## Instructions
Keep narratives short and concrete; name the post kind and the page when it matters. Treat every visitor as a working professional, not a consumer. Never speculate about the content of a referral or a client; stories are about the member's experience of the site, not about the people described in posts.
