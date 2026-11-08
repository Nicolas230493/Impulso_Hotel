import importlib
import importlib.util

from django.apps import AppConfig


class HabitacionesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "habitaciones"

    def ready(self):
        if importlib.util.find_spec(f"{self.name}.signals"):
            importlib.import_module(f"{self.name}.signals")
