"""Secret Manager wrapper - no hardcoded API keys anywhere in the codebase.

External API keys (Spoonacular, USDA nutrition, grocer APIs) are pulled from
GCP Secret Manager at first use and cached in-process. Environment variables
are only used as a *pointer* to the secret ID, never as the secret value.
"""

from __future__ import annotations

import functools
import logging
import os

logger = logging.getLogger(__name__)


@functools.cache
def get_secret(secret_id: str, project_id: str | None = None) -> str | None:
    """Fetch the latest version of ``secret_id`` from Secret Manager.

    Returns ``None`` when the secret is missing so callers can degrade
    gracefully (e.g. use stub data instead of real recipe API).
    """
    project = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        logger.warning("get_secret(%s): no GOOGLE_CLOUD_PROJECT set", secret_id)
        return None
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8")
    except Exception as exc:
        logger.warning("get_secret(%s) failed: %s", secret_id, exc)
        return None


def get_recipe_api_key() -> str | None:
    return get_secret(
        os.environ.get("RECIPE_API_SECRET_ID", "meal-mentor-recipe-api-key")
    )


def get_grocer_api_key() -> str | None:
    return get_secret(
        os.environ.get("GROCER_API_SECRET_ID", "meal-mentor-grocer-api-key")
    )
