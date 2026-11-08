import importlib
import importlib.util

from django.apps import AppConfig


class BiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bi"

    def ready(self):
        if importlib.util.find_spec(f"{self.name}.signals"):
            importlib.import_module(f"{self.name}.signals")
