"""Shared constants for contract tests."""

import uuid

# Test user data
TEST_EMAIL = "test.user@example.com"
TEST_PASSWORD = "securepassword123"
TEST_USERNAME = "testuser"

# API paths
REGISTER_API_PATH = "/auth/register"
POSTS_API_PATH = "/posts"
POSTS_FORM_PAGE_PATH = "/posts/form"

# Stable target-user id used by the admin-actions stub + activation pact.
# Matches `STUB_TARGET_USER_ID` in `infrastructure/servers/consumer.py`.
TARGET_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ACTIVATION_API_PATH = f"/users/{TARGET_USER_ID}/activation"

# Stable post id returned by the post-create handler mock so the consumer can
# match the response shape and the redirect headers without round-tripping a DB.
# Also used as the path id for the edit-form and owner-actions pacts.
STUB_POST_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
POST_EDIT_API_PATH = f"/posts/{STUB_POST_ID}"
POST_EDIT_PAGE_PATH = f"/posts/{STUB_POST_ID}/form"
POST_DELETE_API_PATH = f"/posts/{STUB_POST_ID}"
POST_DETAIL_PAGE_PATH = f"/posts/{STUB_POST_ID}"

# Test post data for the create / edit-form contracts. Posts are
# kind-discriminated; the create form's kind selector + per-kind field
# cluster carry these into the JSON payload. `client_referral` mirrors
# the multi-section intake form (Client Location / Demographics /
# Description / Services / Insurance — see `src/templates/posts/new.html`).
TEST_POST_KIND = "client_referral"

# Section 1: Client Location
TEST_CLIENT_REFERRAL_LOCATION_CITY = "Northampton"
TEST_CLIENT_REFERRAL_LOCATION_STATE = "MA"
TEST_CLIENT_REFERRAL_LOCATION_ZIP = "01060"
TEST_CLIENT_REFERRAL_LOCATION_IN_PERSON = "yes"
TEST_CLIENT_REFERRAL_LOCATION_VIRTUAL = "please_contact"
TEST_CLIENT_REFERRAL_DESIRED_TIME_SLOT = "monday_morning"
# A second slot ticked alongside the first. HTMX `json-enc` only emits a
# JSON array when 2+ checkboxes share the name (single-checkbox payloads
# arrive as bare strings); the contract describes the array form.
TEST_CLIENT_REFERRAL_DESIRED_TIME_SLOT_2 = "wednesday_evening"

# Section 2: Demographics
TEST_CLIENT_REFERRAL_AGE_GROUP = "adults_25_64"
TEST_CLIENT_REFERRAL_LANGUAGE_PREFERRED = "no"

# Section 3: Description
TEST_CLIENT_REFERRAL_DESCRIPTION = "Hello from contract test"

# Section 4: Services
TEST_CLIENT_REFERRAL_SERVICE = "psychotherapy"
# A second service ticked alongside the first; see the time-slot note above.
TEST_CLIENT_REFERRAL_SERVICE_2 = "case_management"
TEST_CLIENT_REFERRAL_PSYCHOTHERAPY_MODALITY = "DBT"

# Section 5: Insurance
TEST_CLIENT_REFERRAL_INSURANCE = "in_network"

# Edited values for the edit-form contract.
EDITED_CLIENT_REFERRAL_DESCRIPTION = "Edited description"
EDITED_CLIENT_REFERRAL_LOCATION_CITY = "Boston"
EDITED_CLIENT_REFERRAL_INSURANCE = "out_of_network"

# --- provider_availability contract values --------------------------------
# Mirror the multi-section intake form (Provider Information / Location /
# Availability / Featured Services / Insurance). Posts are kind-discriminated;
# the create form's kind selector + per-kind field cluster carry these into
# the JSON payload.

PROVIDER_AVAILABILITY_POST_KIND = "provider_availability"

# Section 1: Provider Information
TEST_PROVIDER_AVAILABILITY_PRACTICE_NAME = "Bedlam Clinic"
TEST_PROVIDER_AVAILABILITY_AVAILABLE_PROVIDERS = "Dr. A, Dr. B"

# Section 2: Location (reuses CR location values for cross-kind consistency)
TEST_PROVIDER_AVAILABILITY_LOCATION_CITY = "Northampton"
TEST_PROVIDER_AVAILABILITY_LOCATION_STATE = "MA"
TEST_PROVIDER_AVAILABILITY_LOCATION_ZIP = "01060"

# Section 3: Availability
TEST_PROVIDER_AVAILABILITY_IN_PERSON_SESSIONS = "yes"
TEST_PROVIDER_AVAILABILITY_VIRTUAL_SESSIONS = "please_contact"
# Two slots ticked so HTMX `json-enc-arrays` serializes them as a JSON array.
TEST_PROVIDER_AVAILABILITY_DESIRED_TIME_SLOT = "monday_morning"
TEST_PROVIDER_AVAILABILITY_DESIRED_TIME_SLOT_2 = "wednesday_evening"

# Section 4: Featured Services
TEST_PROVIDER_AVAILABILITY_SERVICE = "psychotherapy"
TEST_PROVIDER_AVAILABILITY_SERVICE_2 = "evaluation"
TEST_PROVIDER_AVAILABILITY_TREATMENT_MODALITY = "DBT"
TEST_PROVIDER_AVAILABILITY_SETTING = "outpatient"
TEST_PROVIDER_AVAILABILITY_SETTING_2 = "iop"
TEST_PROVIDER_AVAILABILITY_CLIENT_FOCUS = "adults seeking trauma-informed care"
TEST_PROVIDER_AVAILABILITY_AGE_GROUP = "adults_25_64"
TEST_PROVIDER_AVAILABILITY_NON_ENGLISH_SERVICES = "no"

# Section 5: Insurance
TEST_PROVIDER_AVAILABILITY_PAYMENT_SITUATION = "in_network"
TEST_PROVIDER_AVAILABILITY_SLIDING_SCALE = True
TEST_PROVIDER_AVAILABILITY_COST = "$150 per session"

# Edited values for the provider_availability edit-form contract.
EDITED_PROVIDER_AVAILABILITY_PRACTICE_NAME = "Edited Clinic"
EDITED_PROVIDER_AVAILABILITY_CLIENT_FOCUS = "Edited focus"
EDITED_PROVIDER_AVAILABILITY_PAYMENT_SITUATION = "out_of_network"

# Provider states
PROVIDER_STATE_USER_DOES_NOT_EXIST = f"User {TEST_EMAIL} does not exist"
PROVIDER_STATE_USER_EXISTS_AND_ACTIVE = f"User {TARGET_USER_ID} exists and is active"
PROVIDER_STATE_POSTS_ACCEPTS_CREATE = "Posts API accepts a create request"
PROVIDER_STATE_POST_EXISTS_AND_OWNED = (
    f"Post {STUB_POST_ID} exists and is owned by the requester"
)

# Consumer / provider Pact identifiers
CONSUMER_NAME_REGISTRATION = "registration-form"
PROVIDER_NAME_AUTH = "auth-api"

CONSUMER_NAME_USER_ADMIN_ACTIONS = "user-admin-actions"
PROVIDER_NAME_USERS = "users-api"

CONSUMER_NAME_POST_CREATE = "post-create-form"
CONSUMER_NAME_POST_EDIT = "post-edit-form"
CONSUMER_NAME_POST_OWNER_ACTIONS = "post-owner-actions"
CONSUMER_NAME_PROVIDER_AVAILABILITY_CREATE = "provider-availability-create-form"
CONSUMER_NAME_PROVIDER_AVAILABILITY_EDIT = "provider-availability-edit-form"
PROVIDER_NAME_POSTS = "posts-api"

# Timeouts
NETWORK_TIMEOUT_MS = 500

# Pact ports (one port per consumer-provider pair)
PACT_PORT_AUTH = 1234
PACT_PORT_USER_ACTIVATION = 1235
PACT_PORT_POST_CREATE = 1236
PACT_PORT_POST_EDIT = 1237
PACT_PORT_POST_DELETE = 1238
PACT_PORT_PROVIDER_AVAILABILITY_CREATE = 1239
PACT_PORT_PROVIDER_AVAILABILITY_EDIT = 1240
