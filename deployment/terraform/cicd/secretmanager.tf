# Secret Manager entries for external API keys used by the tool layer.
# Values are populated out-of-band (see docs) and pulled at runtime via
# app/secrets.py - never via env vars, never hardcoded.

locals {
  meal_mentor_secrets = [
    "meal-mentor-recipe-api-key",
    "meal-mentor-grocer-api-key",
  ]

  secret_project_pairs = merge([
    for project_key, project_id in local.deploy_project_ids : {
      for secret in local.meal_mentor_secrets :
      "${project_key}_${secret}" => { project = project_id, secret = secret }
    }
  ]...)
}

resource "google_secret_manager_secret" "meal_mentor_secrets" {
  for_each = local.secret_project_pairs

  project   = each.value.project
  secret_id = each.value.secret

  replication {
    auto {}
  }

  depends_on = [google_project_service.deploy_project_services]
}
