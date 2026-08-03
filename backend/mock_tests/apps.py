from django.apps import AppConfig


class MockTestsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mock_tests"
    verbose_name = "Mock Tests"
