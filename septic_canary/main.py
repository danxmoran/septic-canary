from functools import lru_cache
import logging
import time
from typing import Callable, Optional

import requests
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, BaseSettings


class AppSettings(BaseSettings):
    house_canary_api_base_url: str = "https://api.housecanary.com"
    house_canary_api_key: str
    house_canary_api_secret: str

    class Config:
        env_file = ".env"


@lru_cache
def get_settings():
    return AppSettings()


def get_now() -> int:
    return int(time.time())


class PropertyDetails(BaseModel):
    has_septic_system: bool


logger = logging.getLogger("uvicorn")
app = FastAPI()


@app.get("/api/v1/property/details")
def property_details(
        street: str,
        unit: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        zip: Optional[int] = None,
        settings: AppSettings = Depends(get_settings),
        get_current_time: Callable[[], int] = Depends(get_now),
) -> PropertyDetails:
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
