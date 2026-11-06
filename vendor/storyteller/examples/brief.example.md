# Site brief: Acme (demo)

Acme is a SaaS tool for small teams. The site has three pages: /pricing.html (plan comparison with a monthly/annual toggle), /signup.html (create an account: email, password, company name), and /docs.html.

Who uses it: individual developers and small-company ops people. Most arrive from Google searches or Hacker News.

What a successful visit looks like: pricing → Start trial → signup form submitted → "Welcome aboard" dialog. For docs visitors, reading for a minute or more counts as success.

Known trouble spots:
- "Company name" is a required field on signup; solo developers often don't have one and stall there.
- The "Go to dashboard" button on the welcome dialog currently does nothing (bug filed 2026-11-01).

Recent changes:
- 2026-11-03: added the annual billing toggle on pricing.

## Tags
signup, pricing_comparison, price_sensitive, form_abandon, validation_error, docs_reading, bounce, bug, completed_signup

## Instructions
Keep narratives short and concrete. When someone stalls on "Company name", mention that we already know about it.
