import importlib
import importlib.util

from django.apps import AppConfig


class SaasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas"

    def ready(self):
        if importlib.util.find_spec(f"{self.name}.signals"):
            importlib.import_module(f"{self.name}.signals")
