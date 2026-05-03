# Templates: HTML presentation layer

The `templates/` directory contains **Jinja2 HTML templates** that define the user interface presentation layer for the application, providing server-side rendered pages with HTMX integration for dynamic interactions.

## Core philosophy: Server-side rendered progressive enhancement

Templates provide **semantic HTML foundation** with progressive enhancement through HTMX, ensuring the application works without JavaScript while providing rich interactive experiences when available.

### What we do

- **Server-side rendering**: Generate complete HTML pages on the server
- **Progressive enhancement**: Base functionality works without JavaScript, enhanced with HTMX
- **Template inheritance**: Use base templates for consistent layout and structure
- **Component organization**: Organize templates by feature/domain area
- **Semantic HTML**: Use proper HTML semantics for accessibility and SEO

**Example**: Base template with HTMX integration:

```html
<!DOCTYPE html>
<html>
  <head>
    <title>{% block title %}App{% endblock %}</title>
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <script src="https://unpkg.com/htmx.org/dist/ext/json-enc.js"></script>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    {% block head %}{% endblock %}
  </head>
  <body>
    {% block content %}{% endblock %}
  </body>
</html>
```

### What we don't do

- **Business logic**: Templates only handle presentation, logic stays in routes/services
- **Data processing**: Data transformation happens in logic layer before templates
- **Authentication logic**: Auth decisions made before template rendering
- **Client-side application state**: Use HTMX for interactions, not complex state management

**Example**: Don't put business logic in templates:

```html
<!-- Bad - business logic in template -->
{% if items|length > limit and user.is_premium %}
<button>Load More</button>
{% endif %}

<!-- Good - logic in route/processing layer -->
{% if can_load_more %}
<button>Load More</button>
{% endif %}
```

## Architecture: Presentation layer with template inheritance

**Base Template -> Feature Templates -> Specific Pages**

Templates use inheritance for consistent layout and feature-specific customization.

## Template organization matrix

| Directory  | Purpose                | Templates                                                              |
| ---------- | ---------------------- | ---------------------------------------------------------------------- |
| **/**      | Base layout and shared | `base.html` - Foundation template                                      |
| **auth/**  | Authentication pages   | login, register, forgot/reset password                                 |
| **users/** | User management        | list, detail, `_admin_actions.html` partial (shared by list & detail)  |
| **posts/** | Posts                  | list, detail, `new.html` + per-kind `edit_*.html` forms, per-kind `_<kind>_fields.html` partials (multi-section intake forms, shared by `new.html` + per-kind `edit_*.html`), `_owner_actions.html` partial (shared by detail) |
| **me/**    | Personal/profile pages | user profile                                                           |

### Reusable partial convention

Files prefixed with `_` (e.g. `_admin_actions.html`) are **shared partials** intended to be `{% include %}`d from multiple full pages. They are not rendered directly by routes. The convention exists so that, e.g., adding a new admin button to `users/_admin_actions.html` automatically appears on both the user list and the user detail page without per-page edits.

A partial documents its required context at the top in a `{# ... #}` comment, and is responsible for its own access guards (`{% if current_user.is_superuser %}` etc). Backend authorization is enforced separately in the logic layer — the template guard is presentation only.

## Directory structure

```
templates/
├── base.html                    # Foundation template with HTMX setup
├── auth/                        # Authentication flow templates
│   ├── login.html              # User login form
│   ├── register.html           # User registration form
│   ├── forgot_password.html    # Password reset request
│   └── reset_password.html     # Password reset form
├── users/                      # User management templates
│   ├── list.html               # User directory listing
│   ├── detail.html             # User detail page
│   └── _admin_actions.html     # Reusable admin-actions partial
├── posts/                      # Post templates (kind-discriminated; unified timeline)
│   ├── list.html               # Post listing — every kind, with kind label per row
│   ├── detail.html             # Post detail — kind label + per-kind field block
│   ├── new.html                # Create-post form: kind selector + per-kind field clusters (script toggles which one is enabled and swaps `data-json-enc-array-fields` to that kind's multi-selects so the other kind's array fields don't leak into the body and trip `extra="forbid"`) → POST /posts
│   ├── edit_client_referral.html       # Edit form for client_referral → PATCH /posts/{id} (delegates to `_client_referral_fields.html`)
│   ├── edit_provider_availability.html # Edit form for provider_availability → PATCH /posts/{id} (delegates to `_provider_availability_fields.html`)
│   ├── _client_referral_fields.html    # Multi-section intake-form partial (Client Location / Demographics / Description / Services / Insurance — 21-cell desired-time grid + 5-checkbox services list). Optional `post` context prefills inputs.
│   ├── _provider_availability_fields.html # Multi-section intake-form partial (Provider Information / Location / Availability / Featured Services / Insurance — 21-cell desired-time grid + 5-checkbox services list + 5-checkbox treatment-settings list + sliding-scale radios). Optional `post` context prefills inputs.
│   └── _owner_actions.html     # Reusable owner-actions partial (Edit + Delete; route layer picks the right edit template per kind)
└── me/                         # Personal user pages
    └── profile.html            # User's profile page
```

## Implementation patterns

### Base template inheritance pattern

All templates extend the base template for consistency:

```html
<!-- base.html - Foundation template -->
<!DOCTYPE html>
<html>
  <head>
    <title>{% block title %}App{% endblock %}</title>
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    {% block head %}{% endblock %} {% if is_development %}
    <!-- LiveReload for development -->
    <script>
      var script = document.createElement('script')
      script.src =
        'http://localhost:{{ livereload_port }}/livereload.js?snipver=1'
      script.async = true
      document.head.appendChild(script)
    </script>
    {% endif %}
  </head>
  <body>
    {% block content %}{% endblock %}
  </body>
</html>

<!-- Feature template extending base -->
{% extends "base.html" %} {% block title %}Users{% endblock
%} {% block content %}
<main>
  <h1>Users</h1>
  <!-- Feature-specific content -->
</main>
{% endblock %}
```

### Htmx integration pattern

Use HTMX for progressive enhancement of forms and interactions:

```html
<!-- Form with HTMX submission -->
<form
  hx-post="/api/[entities]"
  hx-target="#entity-list"
  hx-swap="afterbegin"
  hx-ext="json-enc">
  <label for="name">Name:</label>
  <input type="text" name="name" id="name" required />

  <button type="submit">Create</button>
</form>

<!-- Target container for HTMX updates -->
<div id="entity-list">
  {% for item in items %}
  <!-- Existing items -->
  {% endfor %}
</div>
```

### Template context pattern

Standard context structure passed from routes:

```python
# In route/processing function
def prepare_template_context(request: Request, user: User, data: Any) -> dict:
    """Standard context preparation for templates."""
    return {
        "request": request,          # Required by FastAPI templates
        "current_user": user,        # Current authenticated user
        "is_authenticated": bool(user), # Authentication status
        "is_development": settings.ENVIRONMENT == "development",
        "livereload_port": settings.LIVERELOAD_PORT if settings.ENVIRONMENT == "development" else None,

        # Page-specific data
        "page_title": "Page Title",
        "main_data": data,           # Primary page data
    }
```

## Common template issues and solutions

### Issue: Logic creeping into templates

**Problem**: Complex conditionals and data processing in templates
**Solution**: Move logic to processing layer, pass simple flags to templates

```html
<!-- Bad - complex logic in template -->
{% if items|selectattr("status", "equalto", "active")|list
and items|length < max_count %}
<button>Add Item</button>
{% endif %}

<!-- Good - simple flag from processing layer -->
{% if can_add_item %}
<button>Add Item</button>
{% endif %}
```

### Issue: Missing accessibility features

**Problem**: Templates don't include proper ARIA labels and semantic HTML
**Solution**: Use semantic HTML and proper accessibility attributes

```html
<!-- Good - accessible template structure -->
<main role="main">
  <h1 id="page-title">{{ page_title }}</h1>

  {% if error_message %}
  <div class="error-message" role="alert" aria-live="polite">
    {{ error_message }}
  </div>
  {% endif %}

  <form aria-labelledby="page-title">
    <label for="username">Username:</label>
    <input
      type="text"
      id="username"
      name="username"
      aria-describedby="username-help"
      required />
    <small id="username-help">Enter your username</small>
  </form>
</main>
```

## Development workflow

### Template development with live reload

During development, templates automatically reload when changed:

```python
# Development server includes live reload
if settings.ENVIRONMENT == "development":
    # LiveReload script automatically injected in base.html
    templates.env.auto_reload = True
```

### Template testing approach

Test templates through route integration tests:

```python
# Test template rendering through routes
async def test_user_list_template(client: AsyncClient, authenticated_user):
    response = await client.get("/users")

    assert response.status_code == 200
    assert "Users" in response.text
```

## Tests

Templates are exercised indirectly by the route tests under [`../api/routes/`](../api/routes/) — they assert on the rendered HTML using `selectolax`. There is no separate test file at this directory level. When adding a new template, extend the relevant route test (or add one) to cover its rendering.

## Related documentation

- [API Routes](../api/routes/README.md) - Routes that render these templates
- [Logic Layer](../logic/README.md) - Processing layer that prepares template context
- [Core Layer](../core/README.md) - Template configuration and utilities
