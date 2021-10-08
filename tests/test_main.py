from base64 import b64encode
import json
import time

from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials
import pytest
from requests_mock import Mocker

from septic_canary import main

settings = main.AppSettings(
    house_canary_api_base_url='http://base.url',
    house_canary_api_key='foo',
    house_canary_api_secret='bar',
    api_username='me',
    api_password='supersecretplsnotell'
)
encoded_auth = b64encode(f"{settings.house_canary_api_key}:{settings.house_canary_api_secret}".encode()).decode()
good_creds = HTTPBasicCredentials(username=settings.api_username, password=settings.api_password)


def get_details(**kwargs):
    return main.property_details(settings=settings, credentials=good_creds, **kwargs)


def test_get_property_details_with_septic(requests_mock: Mocker):
    requests_mock.get(
        f"{settings.house_canary_api_base_url}/v2/property/details?address=123+Street&zipcode=98765",
        request_headers={"Authorization": f"Basic {encoded_auth}"},
        text=json.dumps({
            "address_info": {
                "status": {
                    "match": True,
                }
            },
            "property/details": {
                "api_code": 0,
                "result": {
                    "property": {
                        "sewer": "Septic"
                    }
                }
            }
        })
    )

    details = get_details(street="123 Street", zip=98765)
    assert details.has_septic_system


def test_get_property_details_without_septic(requests_mock: Mocker):
    requests_mock.get(
        f"{settings.house_canary_api_base_url}/v2/property/details?address=123+Street&zipcode=98765",
        request_headers={"Authorization": f"Basic {encoded_auth}"},
        text=json.dumps({
            "address_info": {
                "status": {
                    "match": True,
                }
            },
            "property/details": {
                "api_code": 0,
                "result": {
                    "property": {
                        "sewer": "Yes"
                    }
                }
            }
        })
    )

    details = get_details(street="123 Street", zip=98765)
    assert not details.has_septic_system


def test_get_property_details_with_unit_city_state(requests_mock: Mocker):
    requests_mock.get(
        f"{settings.house_canary_api_base_url}/v2/property/details?address=123+Street&unit=10f&city=Big&state=MA",
        request_headers={"Authorization": f"Basic {encoded_auth}"},
        text=json.dumps({
            "address_info": {
                "status": {
                    "match": True,
                }
            },
            "property/details": {
                "api_code": 0,
                "result": {
                    "property": {
                        "sewer": "Septic"
                    }
                }
            }
        })
    )

    details = get_details(street="123 Street", unit="10f", city="Big", state="MA")
    assert details.has_septic_system


def test_get_property_details_bad_auth():
    with pytest.raises(HTTPException) as exc_info:
        main.property_details(street='', settings=settings,
                              credentials=HTTPBasicCredentials(username='foo', password='bar'))
    assert exc_info.value.status_code == 401


def test_get_property_details_missing_params():
    with pytest.raises(HTTPException) as exc_info:
        get_details(street="123 Street", city="Big")
    assert exc_info.value.status_code == 422


def test_get_property_details_bad_internal_auth(requests_mock: Mocker):
    requests_mock.get(
        f"{settings.house_canary_api_base_url}/v2/property/details?address=123+Street&zipcode=98765",
        request_headers={"Authorization": f"Basic {encoded_auth}"},
        status_code=401,
        text=json.dumps({"message": "Authentication Failed", "code": 401})
    )

    with pytest.raises(HTTPException) as exc_info:
        get_details(street="123 Street", zip=98765)
    assert exc_info.value.status_code == 500


def test_get_property_details_malformed_internal_request(requests_mock: Mocker):
    # Simulate the HomeCanary API changing out from under us.
    requests_mock.get(
        f"{settings.house_canary_api_base_url}/v2/property/details?address=123+Street&zipcode=98765",
        request_headers={"Authorization": f"Basic {encoded_auth}"},
        status_code=400,
        text=json.dumps({"message": "Missing required parameter in the query string"})
    )

    with pytest.raises(HTTPException) as exc_info:
        get_details(street="123 Street", zip=98765)
    assert exc_info.value.status_code == 500


def test_get_property_details_address_fails_resolution(requests_mock: Mocker):
    requests_mock.get(
        f"{settings.house_canary_api_base_url}/v2/property/details?address=123+Street&zipcode=98765",
        request_headers={"Authorization": f"Basic {encoded_auth}"},
        text=json.dumps({
            "address_info": {
                "status": {
                    "match": False,
                }
            },
        })
    )

    with pytest.raises(HTTPException) as exc_info:
        get_details(street="123 Street", zip=98765)
    assert exc_info.value.status_code == 404


def test_get_property_details_rate_limit(requests_mock: Mocker):
    now = int(time.time())
    requests_mock.get(
        f"{settings.house_canary_api_base_url}/v2/property/details?address=123+Street&zipcode=98765",
        request_headers={"Authorization": f"Basic {encoded_auth}"},
        status_code=429,
        text=json.dumps({"message": "Too Many Requests"}),
        headers={"X-RateLimit-Reset": str(now + 1000)},
    )

    with pytest.raises(HTTPException) as exc_info:
        get_details(street="123 Street", zip=98765, get_current_time=lambda: now)
    assert exc_info.value.status_code == 429
    assert int(exc_info.value.headers["Retry-After"]) == 1000
