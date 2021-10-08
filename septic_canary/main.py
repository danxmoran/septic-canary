from functools import lru_cache
import logging
import secrets
import time
from typing import Callable, Optional

import requests
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, BaseSettings


class AppSettings(BaseSettings):
    """
    AppSettings models the configuration used by the service.

    Settings can be injected either via env var, or via a `.env` file.
    """
    house_canary_api_base_url: str = "https://api.housecanary.com"
    house_canary_api_key: str
    house_canary_api_secret: str

    api_username: str
    api_password: str

    class Config:
        env_file = ".env"


@lru_cache
def get_settings():
    """
    Load application settings from the environment / from disk.

    The settings returned by this function are cached.
    """
    return AppSettings()


def get_now() -> int:
    """
    Get the current UTC epoch in seconds.
    """
    return int(time.time())


class PropertyDetails(BaseModel):
    """
    PropertyDetails models all information about a property returned by this service.
    """
    has_septic_system: bool


logger = logging.getLogger("uvicorn")
app = FastAPI()
security = HTTPBasic()

@app.get("/api/v1/property/details")
def property_details(
        street: str,
        unit: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        zip: Optional[int] = None,
        settings: AppSettings = Depends(get_settings),
        credentials: HTTPBasicCredentials = Depends(security),
        get_current_time: Callable[[], int] = Depends(get_now),
) -> PropertyDetails:
    """
    Look up details about a requested property.

    `address` must be provided, along with either `zip` or both `city` and `state`.

    :param street: Street address of the property
    :param unit: Unit of the property within the building at `street`
    :param city: City containing the property
    :param state: State containing the property
    :param zip: ZIP code containing the property
    :param settings: Application settings
    :param credentials: HTTP Basic credentials passed in the request
    :param get_current_time: No-arg function that returns the current UTC epoch in seconds
    :return: Details about the specified property
    """
    # Authenticate the request.
    correct_username = secrets.compare_digest(credentials.username, settings.api_username)
    correct_password = secrets.compare_digest(credentials.password, settings.api_password)
    if not (correct_username and correct_password):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})

    # Check we have enough information to locate the property.
    if not zip and not (city and state):
        raise HTTPException(status_code=422, detail="either 'zip' or both 'city' and 'state' must be specified")

    # Filter out any unset/empty parameters.
    lookup_params = dict(
        (k, v) for k, v in
        [("address", street), ("unit", unit), ("city", city), ("state", state), ("zipcode", zip)]
        if v
    )

    # Request details from HomeCanary.
    res = requests.get(
        f"{settings.house_canary_api_base_url}/v2/property/details",
        params=lookup_params,
        auth=(settings.house_canary_api_key, settings.house_canary_api_secret),
    )
    if res.status_code != 200:
        logger.error("Request to HouseCanary failed: %s", res.json())

        # Pass rate-limit errors through to the client so they know to back off.
        if res.status_code == 429:
            # HouseCanary returns `X-RateLimit-Reset: <UTC-epoch-second when it's OK to retry>`.
            # A more standard response would be `Retry-After: <seconds to wait before retrying>`
            # We translate between the two forms.
            limit_reset_time = int(res.headers["X-RateLimit-Reset"])
            now = get_current_time()
            retry_after = limit_reset_time - now
            raise HTTPException(status_code=429, detail="Too many requests", headers={"Retry-After": retry_after})

        # Otherwise report an internal server error, as any other error code means we sent HomeCanary a
        # malformed/mis-authenticated request.
        raise HTTPException(
            status_code=500,
            detail="an error occurred while looking up property details, see server logs for more info",
        )
    res_body = res.json()

    # Check the HomeCanary response to see if it was able to resolve the address.
    resolution_status = res_body["address_info"]["status"]
    if not bool(resolution_status["match"]):
        raise HTTPException(status_code=404, detail="could not resolve address using given parameters")

    # Extract the specific details we care about from the response.
    property_details = res_body["property/details"]["result"]["property"]
    property_has_septic_system = "sewer" in property_details and property_details["sewer"].lower() == "septic"

    return PropertyDetails(has_septic_system=property_has_septic_system)
