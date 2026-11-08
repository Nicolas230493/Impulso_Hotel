from django.core.management.base import BaseCommand

from core.permisos import sincronizar_roles


class Command(BaseCommand):
    help = "Crea los grupos de roles y les asigna los permisos por módulo y acción."

    def handle(self, *args, **options):
        sincronizar_roles()
        self.stdout.write(self.style.SUCCESS("Roles sincronizados."))
