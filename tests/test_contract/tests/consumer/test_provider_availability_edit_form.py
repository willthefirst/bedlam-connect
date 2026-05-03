"""Consumer contract: filling and submitting the provider_availability
edit-post form.

Verifies that the form rendered by
`templates/posts/edit_provider_availability.html` (mounted via the
`posts_pages` flag on the consumer server, with `?kind=provider_availability`
to select the PA stub) issues `PATCH /posts/{id}` with a JSON body matching
`ProviderAvailabilityUpdate`.
"""

import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_PROVIDER_AVAILABILITY_EDIT,
    EDITED_PROVIDER_AVAILABILITY_CLIENT_FOCUS,
    EDITED_PROVIDER_AVAILABILITY_PAYMENT_SITUATION,
    EDITED_PROVIDER_AVAILABILITY_PRACTICE_NAME,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_PROVIDER_AVAILABILITY_EDIT,
    POST_EDIT_API_PATH,
    POST_EDIT_PAGE_PATH,
    PROVIDER_AVAILABILITY_POST_KIND,
    PROVIDER_NAME_POSTS,
    PROVIDER_STATE_POST_EXISTS_AND_OWNED,
    STUB_POST_ID,
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
async def test_consumer_provider_availability_edit_form_interaction(
    origin_with_routes: str, page: Page
):
    pact = setup_pact(
        CONSUMER_NAME_PROVIDER_AVAILABILITY_EDIT,
        PROVIDER_NAME_POSTS,
        port=PACT_PORT_PROVIDER_AVAILABILITY_EDIT,
    )
    mock_server_uri = pact.uri
    # The edit stub picks the PA template when `?kind=provider_availability`.
    edit_page_url = (
        f"{origin_with_routes}{POST_EDIT_PAGE_PATH}?kind=provider_availability"
    )
    full_mock_url = f"{mock_server_uri}{POST_EDIT_API_PATH}"

    expected_request_headers = {"Content-Type": "application/json"}
    # The edit form submits *every* field (the entire provider_availability
    # cluster is rendered with current values); pact `Like` matchers keep the
    # contract focused on the shape rather than specific values.
    expected_request_body = {
        "kind": Like(PROVIDER_AVAILABILITY_POST_KIND),
        "practice_name": Like(EDITED_PROVIDER_AVAILABILITY_PRACTICE_NAME),
        "available_providers": Like("Dr. A, Dr. B"),
        "location_city": Like("Northampton"),
        "location_state": Like("MA"),
        "location_zip": Like("01060"),
        "in_person_sessions": Like("yes"),
        "virtual_sessions": Like("please_contact"),
        "desired_times": [Like("monday_morning"), Like("wednesday_evening")],
        "services": [Like("psychotherapy"), Like("evaluation")],
        "treatment_modality": Like("DBT"),
        "settings": [Like("outpatient"), Like("iop")],
        "client_focus": Like(EDITED_PROVIDER_AVAILABILITY_CLIENT_FOCUS),
        "age_group": Like("adults_25_64"),
        "non_english_services": Like("no"),
        "payment_situation": Like(EDITED_PROVIDER_AVAILABILITY_PAYMENT_SITUATION),
        "sliding_scale": Like(True),
        "cost": Like("$150 per session"),
    }
    expected_response_body = {"id": Like(str(STUB_POST_ID))}

    (
        pact.given(PROVIDER_STATE_POST_EXISTS_AND_OWNED)
        .upon_receiving(
            "a request to edit a provider_availability post via the edit-post form"
        )
        .with_request(
            method="PATCH",
            path=POST_EDIT_API_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "application/json"},
            body=expected_response_body,
        )
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=POST_EDIT_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="PATCH",
    )

    with pact:
        await page.goto(edit_page_url)
        await page.wait_for_selector("#pa-practice-name")
        await page.locator("#pa-practice-name").fill(
            EDITED_PROVIDER_AVAILABILITY_PRACTICE_NAME
        )
        await page.locator("#pa-client-focus").fill(
            EDITED_PROVIDER_AVAILABILITY_CLIENT_FOCUS
        )
        await page.locator("#pa-payment-situation").select_option(
            EDITED_PROVIDER_AVAILABILITY_PAYMENT_SITUATION
        )
        await page.locator("input[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)
