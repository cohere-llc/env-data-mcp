"""Constants for the ARM Live adapter."""

from __future__ import annotations

from types import MappingProxyType

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "Free and open (ARM data use guidelines; a free ARM account is needed for data)",
        "license_url": "https://www.arm.gov/guidance/datause/generalguidelines",
        "citation": (
            "Atmospheric Radiation Measurement (ARM) user facility, U.S. Department of Energy, "
            "Office of Science — ARM Live data service, https://adc.arm.gov/armlive/"
        ),
        "description": "The files ARM holds for a datastream over a date range (ARM Live query).",
        "description_url": "https://adc.arm.gov/armlive/",
        "acknowledgements": "Data were obtained from the ARM user facility, a DOE Office of "
        "Science user facility managed by the Biological and Environmental Research program.",
    }
)

SOURCE = "arm_live"
KEY_NAME = "ARM_LIVE_TOKEN"  # the value is ``user:token``, as ARM issues it
SIGNUP_URL = "https://adc.arm.gov/armuserreg/#/new"
ARMLIVE_BASE_URL = "https://adc.arm.gov/armlive/livedata"
TTL_S = 60 * 60
# ARM Live accepts the credential ONLY as ``?user=user:token`` (no header form). The URL is
# therefore never logged: feeds.RedactCredentials rewrites ``user=`` in every httpx/httpcore record.
CREDENTIAL_IN_URL = "query"
