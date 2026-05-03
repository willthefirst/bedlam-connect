"""Consumer contract: filling and submitting the new-post form for the
`provider_availability` kind.

Mirrors `test_post_form.py` (which covers the `client_referral` cluster) by
selecting the PA kind in the radio and asserting the intercepted POST body
matches `ProviderAvailabilityCreate`. The contract surface is the new-post
form template + its `provider_availability` field cluster
(`templates/posts/_provider_availability_fields.html`) and the route's
request shape.
"""

import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_PROVIDER_AVAILABILITY_CREATE,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_PROVIDER_AVAILABILITY_CREATE,
    POSTS_API_PATH,
    POSTS_FORM_PAGE_PATH,
    PROVIDER_AVAILABILITY_POST_KIND,
    PROVIDER_NAME_POSTS,
    PROVIDER_STATE_POSTS_ACCEPTS_CREATE,
    STUB_POST_ID,
    TEST_PROVIDER_AVAILABILITY_AGE_GROUP,
    TEST_PROVIDER_AVAILABILITY_AVAILABLE_PROVIDERS,
    TEST_PROVIDER_AVAILABILITY_CLIENT_FOCUS,
    TEST_PROVIDER_AVAILABILITY_COST,
    TEST_PROVIDER_AVAILABILITY_DESIRED_TIME_SLOT,
    TEST_PROVIDER_AVAILABILITY_DESIRED_TIME_SLOT_2,
    TEST_PROVIDER_AVAILABILITY_IN_PERSON_SESSIONS,
    TEST_PROVIDER_AVAILABILITY_LOCATION_CITY,
    TEST_PROVIDER_AVAILABILITY_LOCATION_STATE,
    TEST_PROVIDER_AVAILABILITY_LOCATION_ZIP,
    TEST_PROVIDER_AVAILABILITY_NON_ENGLISH_SERVICES,
    TEST_PROVIDER_AVAILABILITY_PAYMENT_SITUATION,
    TEST_PROVIDER_AVAILABILITY_PRACTICE_NAME,
    TEST_PROVIDER_AVAILABILITY_SERVICE,
    TEST_PROVIDER_AVAILABILITY_SERVICE_2,
    TEST_PROVIDER_AVAILABILITY_SETTING,
    TEST_PROVIDER_AVAILABILITY_SETTING_2,
    TEST_PROVIDER_AVAILABILITY_SLIDING_SCALE,
    TEST_PROVIDER_AVAILABILITY_TREATMENT_MODALITY,
    TEST_PROVIDER_AVAILABILITY_VIRTUAL_SESSIONS,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


@pytest.mark.parametrize(
    "origin_with_routes",
    [{"posts_pages": True, "auth_pages": False}],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_provider_availability_create_form_interaction(
    origin_with_routes: str, page: Page
):
    """Submit the new-post form (provider_availability kind selected); assert
    the intercepted request matches the contracted shape (POST /posts with the
    full multi-section intake-form JSON body)."""
    pact = setup_pact(
        CONSUMER_NAME_PROVIDER_AVAILABILITY_CREATE,
        PROVIDER_NAME_POSTS,
        port=PACT_PORT_PROVIDER_AVAILABILITY_CREATE,
    )
    mock_server_uri = pact.uri
    form_page_url = f"{origin_with_routes}{POSTS_FORM_PAGE_PATH}"
    full_mock_url = f"{mock_server_uri}{POSTS_API_PATH}"

    expected_request_headers = {"Content-Type": "application/json"}
    expected_request_body = {
        "kind": Like(PROVIDER_AVAILABILITY_POST_KIND),
        "practice_name": Like(TEST_PROVIDER_AVAILABILITY_PRACTICE_NAME),
        "available_providers": Like(TEST_PROVIDER_AVAILABILITY_AVAILABLE_PROVIDERS),
        "location_city": Like(TEST_PROVIDER_AVAILABILITY_LOCATION_CITY),
        "location_state": Like(TEST_PROVIDER_AVAILABILITY_LOCATION_STATE),
        "location_zip": Like(TEST_PROVIDER_AVAILABILITY_LOCATION_ZIP),
        "in_person_sessions": Like(TEST_PROVIDER_AVAILABILITY_IN_PERSON_SESSIONS),
        "virtual_sessions": Like(TEST_PROVIDER_AVAILABILITY_VIRTUAL_SESSIONS),
        "desired_times": [
            Like(TEST_PROVIDER_AVAILABILITY_DESIRED_TIME_SLOT),
            Like(TEST_PROVIDER_AVAILABILITY_DESIRED_TIME_SLOT_2),
        ],
        "services": [
            Like(TEST_PROVIDER_AVAILABILITY_SERVICE),
            Like(TEST_PROVIDER_AVAILABILITY_SERVICE_2),
        ],
        "treatment_modality": Like(TEST_PROVIDER_AVAILABILITY_TREATMENT_MODALITY),
        "settings": [
            Like(TEST_PROVIDER_AVAILABILITY_SETTING),
            Like(TEST_PROVIDER_AVAILABILITY_SETTING_2),
        ],
        "client_focus": Like(TEST_PROVIDER_AVAILABILITY_CLIENT_FOCUS),
        "age_group": Like(TEST_PROVIDER_AVAILABILITY_AGE_GROUP),
        "non_english_services": Like(TEST_PROVIDER_AVAILABILITY_NON_ENGLISH_SERVICES),
        "payment_situation": Like(TEST_PROVIDER_AVAILABILITY_PAYMENT_SITUATION),
        "sliding_scale": Like(TEST_PROVIDER_AVAILABILITY_SLIDING_SCALE),
        "cost": Like(TEST_PROVIDER_AVAILABILITY_COST),
    }
    expected_response_body = {"id": Like(str(STUB_POST_ID))}

    (
        pact.given(PROVIDER_STATE_POSTS_ACCEPTS_CREATE)
        .upon_receiving(
            "a request to create a provider_availability post via the new-post form"
        )
        .with_request(
            method="POST",
            path=POSTS_API_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=201,
            headers={"Content-Type": "application/json"},
            body=expected_response_body,
        )
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=POSTS_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="POST",
    )

    with pact:
        await page.goto(form_page_url)
        await page.wait_for_selector('input[type="radio"][name="kind"]')
        await page.locator(
            f'input[type="radio"][name="kind"][value="{PROVIDER_AVAILABILITY_POST_KIND}"]'
        ).check()
        await page.locator("#pa-practice-name").fill(
            TEST_PROVIDER_AVAILABILITY_PRACTICE_NAME
        )
        await page.locator("#pa-available-providers").fill(
            TEST_PROVIDER_AVAILABILITY_AVAILABLE_PROVIDERS
        )
        await page.locator("#pa-location-city").fill(
            TEST_PROVIDER_AVAILABILITY_LOCATION_CITY
        )
        await page.locator("#pa-location-state").select_option(
            TEST_PROVIDER_AVAILABILITY_LOCATION_STATE
        )
        await page.locator("#pa-location-zip").fill(
            TEST_PROVIDER_AVAILABILITY_LOCATION_ZIP
        )
        await page.locator("#pa-in-person-sessions").select_option(
            TEST_PROVIDER_AVAILABILITY_IN_PERSON_SESSIONS
        )
        await page.locator("#pa-virtual-sessions").select_option(
            TEST_PROVIDER_AVAILABILITY_VIRTUAL_SESSIONS
        )
        await page.locator(
            f'input[type="checkbox"][name="desired_times"][value="{TEST_PROVIDER_AVAILABILITY_DESIRED_TIME_SLOT}"]'
        ).check()
        await page.locator(
            f'input[type="checkbox"][name="desired_times"][value="{TEST_PROVIDER_AVAILABILITY_DESIRED_TIME_SLOT_2}"]'
        ).check()
        await page.locator(
            f'input[type="checkbox"][name="services"][value="{TEST_PROVIDER_AVAILABILITY_SERVICE}"]'
        ).check()
        await page.locator(
            f'input[type="checkbox"][name="services"][value="{TEST_PROVIDER_AVAILABILITY_SERVICE_2}"]'
        ).check()
        await page.locator("#pa-treatment-modality").fill(
            TEST_PROVIDER_AVAILABILITY_TREATMENT_MODALITY
        )
        await page.locator(
            f'input[type="checkbox"][name="settings"][value="{TEST_PROVIDER_AVAILABILITY_SETTING}"]'
        ).check()
        await page.locator(
            f'input[type="checkbox"][name="settings"][value="{TEST_PROVIDER_AVAILABILITY_SETTING_2}"]'
        ).check()
        await page.locator("#pa-client-focus").fill(
            TEST_PROVIDER_AVAILABILITY_CLIENT_FOCUS
        )
        await page.locator("#pa-age-group").select_option(
            TEST_PROVIDER_AVAILABILITY_AGE_GROUP
        )
        await page.locator("#pa-non-english-services").select_option(
            TEST_PROVIDER_AVAILABILITY_NON_ENGLISH_SERVICES
        )
        await page.locator("#pa-payment-situation").select_option(
            TEST_PROVIDER_AVAILABILITY_PAYMENT_SITUATION
        )
        sliding_value = "true" if TEST_PROVIDER_AVAILABILITY_SLIDING_SCALE else "false"
        await page.locator(
            f'input[type="radio"][name="sliding_scale"][value="{sliding_value}"]'
        ).check()
        await page.locator("#pa-cost").fill(TEST_PROVIDER_AVAILABILITY_COST)
        await page.locator("input[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)
