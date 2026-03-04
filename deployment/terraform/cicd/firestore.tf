# Firestore Native databases for the staging and prod projects. Meal Mentor's
# memory layer connects to the (default) database in whichever project the
# service is deployed into.

resource "google_firestore_database" "staging_db" {
  project                     = var.staging_project_id
  name                        = "(default)"
  location_id                 = var.region
  type                        = "FIRESTORE_NATIVE"
  concurrency_mode            = "OPTIMISTIC"
  app_engine_integration_mode = "DISABLED"

  depends_on = [google_project_service.deploy_project_services]
}

resource "google_firestore_database" "prod_db" {
  project                     = var.prod_project_id
  name                        = "(default)"
  location_id                 = var.region
  type                        = "FIRESTORE_NATIVE"
  concurrency_mode            = "OPTIMISTIC"
  app_engine_integration_mode = "DISABLED"

  depends_on = [google_project_service.deploy_project_services]
}
