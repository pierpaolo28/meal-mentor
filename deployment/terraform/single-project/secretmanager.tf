# Secret Manager entries used by the tool layer. Values are NOT stored in
# Terraform state: operators upload them out-of-band with:
#
#   echo -n "<key>" | gcloud secrets versions add meal-mentor-recipe-api-key --data-file=-
#
# The app never reads env-var-set keys - it always resolves via the Secret
# Manager client in app/secrets.py.

resource "google_secret_manager_secret" "recipe_api_key" {
  project   = var.project_id
  secret_id = "meal-mentor-recipe-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret" "grocer_api_key" {
  project   = var.project_id
  secret_id = "meal-mentor-grocer-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.services]
}

# The application service account is granted secretAccessor via app_sa_roles
# in variables.tf, so no per-secret IAM is needed here.
