# Firestore Native database used by the memory layer for pantry / meal plans /
# preferences / learnings. Uses the (default) database so no extra config is
# required in the app.

resource "google_firestore_database" "meal_mentor_db" {
  project                     = var.project_id
  name                        = "(default)"
  location_id                 = var.region
  type                        = "FIRESTORE_NATIVE"
  concurrency_mode            = "OPTIMISTIC"
  app_engine_integration_mode = "DISABLED"

  depends_on = [google_project_service.services]
}
