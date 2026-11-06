# Domain templates

Per-entity Jinja templates. One cluster directory per resource (`clinicians/`, `users/`, `posts/`, `favorites/`, `auth/`); cluster-local partials are prefixed `_`.

Chrome, shared macros, and the generic view-type templates live in [`../../framework/templates/`](../../framework/templates/) — see its README for the full contract, including the page-chrome strips, the layering rule, and the four view-type templates (`views/list.html`, `views/detail.html`, `views/form_new.html`, `views/form_edit.html`) that this directory's pages extend.

## Per-cluster grammar

A resource cluster `<entity>/` typically contains:

- `list.html` — extends `views/list.html`. Declares `resource_label`, an optional `actions` block (right-aligned toolbar items, each an `<li>` inside `<menu class="toolbar-right">`), and a `list_body` block: a `<section id="<collection>-list">` of cards rendered through `_shared/_card.html` (or a resource-specific card macro like `_shared/_clinician_card.html`). When the spec declares `filters=(…)`, the list view automatically wraps `list_body` in a two-column browse layout with the filter form in a sidebar — no per-template wiring needed. The toolbar never carries a filter link; the results column opens with a plain `<header>` that states whether the result set is filtered and links the filter count to the full search page. (`posts/list.html` additionally suppresses the toolbar entirely — no page `<h1>` or Create action, since the global nav "+ Post" button covers posting — and renders no Referrals/Openings intent toggle.)
- `search.html` — extends `views/search.html`. One-line stub setting the `resource_label` breadcrumb for entities whose spec declares `filters=(…)` — declaring filters auto-mounts `/<collection>/search`. Renders one form control per declared `Filter` on the spec.
- `detail.html` — extends `views/detail.html`. Declares `resource_label`, `current_label`, `resource_url`, optional `actions`, and `content`.
- `form_new.html` — extends `views/form_new.html`. Declares `resource_label`, `resource_url`, and the form body in `form_content` (rendered inside the `entity-form-page` wrapper provided by the view template).
- `form_edit.html` — extends `views/form_edit.html`. Declares `resource_label`, `current_label`, `resource_url`, `resource_detail_url`, and the form body in `form_content` (same wrapper).
- `_<role>_actions.html` (cluster-local partial) — owner/admin action button clusters for the entity, `{% include %}`d from the detail page's `actions` block or the card footer on the list page.

An owned-subentity cluster whose form fields already live in a single `_form_<entity>.html` partial may **skip both** `form_new.html` and `form_edit.html` by setting `templates.form_partial="<cluster>/_form_<entity>.html"` on its `EntitySpec` — the spec-driven `views/subresource_form_{new,edit}.html` view templates `{% include %}` the partial inside the standard form chrome. The clinician credential trio uses this shape, with its three cluster directories grouped under `clinician_credentials/` because they share one factory-declared spec shape — the factory (`domain/specs/credentials/_credential.py`) declares the grouped template paths explicitly, since grouping deviates from the `<url_collection>/<verb>.html` convention default. Each carries only `list.html` and `_form_<entity>.html`. See [`../../framework/templates/README.md` § "Spec-driven form pages"](../../framework/templates/README.md) for the partial's context contract.

Subresource lists (e.g. `/users/{id}/clinicians`) override `{% block breadcrumb %}` to pass a multi-segment chain (`[("Users", …), (username, /users/<id>), ("Clinicians", None)]`); the breadcrumb macro renders only the deepest clickable parent as a back link, so the override's job is to shift the back target one level up the tree (here: back to the user) rather than to the collection. The page still inherits the list view's toolbar + content shape from `views/list.html`. See `users/clinicians_list.html`.

Pages that don't fit the resource grammar — the `/auth/*` flow's centered single-card layout — extend `base.html` directly and compose the `_shared/` macros by hand.

Post templates nest under a single `posts/` cluster — all per-kind templates live directly under it following the default `PostKindSpec` convention (no template path overrides), with a `_shared/` for cross-kind partials:

```
posts/
├── _shared/              ← cross-kind partials (_item, _facts_block, _owner_actions, …)
├── list.html, detail.html, search.html  ← whole-supertype /posts face
├── form_new.html (picker), form_edit.html (kind-dispatch fallback)
├── new_referral.html, edit_referral.html, _form_referral.html
├── new_clinician_opening.html, edit_clinician_opening.html, _form_clinician_opening.html
└── new_program_intake.html, edit_program_intake.html, _form_program_intake.html
```

The handler sets `template_name = POST_KINDS[kind].create_template` (or `edit_template`) to pick the right per-kind form by the `?kind=` URL param or the row's stored kind. The post spec in [`../specs/posts/_base.py`](../specs/posts/_base.py) sets `templates=Templates(list="posts/list.html", …)` for the whole-supertype face's primary verbs.

The cross-resource import lint ([`scripts/dev/template_imports_check.py`](../../../scripts/dev/template_imports_check.py)) permits per-kind templates in `posts/` to import from `posts/_shared/` — that's how the per-kind templates pull in shared post-card partials without crossing a boundary.

The services list is the first row of `_facts_block`'s `<dl>` rather than its own partial (see #628).

**Content that must never be session-recorded** carries `data-no-record` — the block selector of the Storyteller snippet rendered by `base.html` (see [`../logic/storyteller/README.md`](../logic/storyteller/README.md)). Typed input is always masked by the snippet; this attribute is for *displayed* text about a person other than the viewer. The domain decides *which* content that is, once, in the view model (`post_card_view(...).describes_client` is true for referrals, whose facts describe a client); templates only translate the flag into the attribute, via `facts_block(no_record=…)`, `card(no_record=…)`, or the attribute on a wrapper. Mark the smallest element that holds the text, never a whole page or row, so recordings keep the page's shape and the actions on it (a referral's Connect panel stays recordable).

The auth-flow pages (`auth/login.html`, `auth/register.html`, `auth/forgot_password.html`, `auth/reset_password.html`, `auth/verify.html`) each render a single `<section class="auth-page">`. The `.auth-page` rule in [`../../framework/static/css/framework.css`](../../framework/static/css/framework.css) caps the form at 28rem and centers it; **no card chrome** is applied. Card chrome (background, border, padding, header/footer bands) is reserved for list-item cards — plain `<article>` rendered through `_shared/_card.html` — which get the chrome from Pico's default `<article>` element styling. Detail-page bodies render their facts blocks directly under `<main>` with no wrapper, and the `<section class="auth-page">` is a layout hook for the max-width cap; the wrapping `<main class="container">` already centers and caps page content.

## Copy style guide

Every label, legend, help string, button, and intro paragraph in `src/domain/templates/` follows the rules below. The audience is mental-health clinicians — copy reads as concise plain English, not clinical jargon. Pinned by [`test_copy_conventions.py`](test_copy_conventions.py); a violation surfaces as a test failure, not a code review note.

### Labels and legends

- **Sentence case.** `First name`, `In-network carriers`, `Treatment settings` — not `First Name` or `Treatment Settings`. Acronyms keep their canonical case (`NPI`, `ZIP`, `DBT`).
- **No trailing punctuation** unless the label is genuinely a question. `Sliding scale?` yes; `Last name.` no.
- **No app-internal abbreviations.** `Organization`, never `Org`. Domain acronyms every clinician already says aloud (`NPI`, `ZIP`) stay.

### Help text (`help=`)

- **Full sentence, period at the end.** `Adding your NPI lets us cross-check your identity against NPPES.` not `Adding your NPI lets us cross-check your identity against NPPES`.
- **Specific.** Explain *what the value is for*, not that the field exists. `For example: DBT, EMDR, IFS.` beats `Free text.`.
- **Never write `help="Optional."`.** Forms carry no visual required/optional indicator, so don't restate optionality in prose either — leave optional fields' help to describe the value, nothing more. See below.
- If the same help string appears in two or more forms, move it to [`../../framework/templates/_shared/form_copy.html`](../../framework/templates/_shared/form_copy.html) and import it.

### Required vs. optional fields

Pass `required=` to any form-field macro — never mark up requiredness yourself. The *mechanism* (it emits the control's HTML `required` attribute, and there is **no visual label decoration**) lives in the [`form_fields.html`](../../framework/templates/_shared/form_fields.html) docstring. The copy consequence is what belongs here: since required and optional fields look identical, **never announce optionality in prose** — no `(optional)`, no `help="Optional."`, no fieldset-level "everything below is optional" lines.

```jinja
{# Required (the default for most macros) #}
{{ text_field("last_name", "Last name", help="As it appears on your license.") }}

{# Optional — pass required=False; no "Optional." prose #}
{{ text_field("npi", "NPI", required=False, help="Adding your NPI lets us cross-check your identity against NPPES.") }}

{# Bad — don't announce optionality in prose #}
{{ text_field("npi", "NPI", required=False, help="Optional. Adding your NPI lets us cross-check your identity against NPPES.") }}
```

### Buttons

- **Verb-noun, sentence case.** `Create program`, `Post referral`, `Save changes`, `Send reset link`.
- **Create / edit submit pattern.** Create forms use `entity_create_label(spec.name, kind=...)` so the submit button text matches the H1 (`Create Opening` everywhere). Edit forms use `Save changes` — every edit form, no exceptions; this is the `actions(...)` macro's `wrapper="form"` default, so edit pages just omit `submit_label` and inherit it (pinned by `test_form_layout_submit_label_defaults_to_save_changes` in `../../framework/templates/_shared/test_actions.py`). The matching create-form structural pin lives in `entity_create_label` (see [`../../framework/templates/README.md` § "Create / filter labels"](../../framework/templates/README.md)).

### Vocabulary

One word per concept, no synonyms. Replace any of the variants below in any new copy:

| Concept                    | Word                | Don't use                                |
| -------------------------- | ------------------- | ---------------------------------------- |
| Person who treats          | clinician           | provider, practitioner, therapist        |
| Person treated             | client              | patient                                  |
| Practice / employer entity | organization        | practice, clinic, group, agency          |
| Delivery format            | in-person / virtual | telehealth, remote, online               |
| The post type announcing availability for individual clinicians | opening | listing, slot, position |
| The post type announcing program-level intake | intake | enrollment, admission window |
| The post type seeking placement for a client | referral | seeker post, lead |



### Shared microcopy

Strings repeated across forms live in [`../../framework/templates/_shared/form_copy.html`](../../framework/templates/_shared/form_copy.html). Today:

- `org_picker_help()` — the "Can't find your organization?" hint for every Org-FK picker.
- `modality_help()` — the `e.g. DBT, EMDR, IFS` example for the treatment-modality free-text field.
- `select_all_help()` — the `Select all that apply.` hint for multi-choice demographics.

If a new string would otherwise live in two forms, add it here.

## Tests

Exercised indirectly via route tests under [`../routes/`](../routes/), plus [`test_copy_conventions.py`](test_copy_conventions.py) (this directory) which scans every template for forbidden patterns (literal `Optional.` help strings, `Org` abbreviation, etc.). Selector and fixture conventions live in [`../../../tests/README.md`](../../../tests/README.md).
