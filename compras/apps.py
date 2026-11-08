import importlib
import importlib.util

from django.apps import AppConfig


class ComprasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "compras"

    def ready(self):
        if importlib.util.find_spec(f"{self.name}.signals"):
            importlib.import_module(f"{self.name}.signals")
