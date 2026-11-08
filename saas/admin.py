from django.contrib import admin

from .models import (
    AceptacionLegal,
    ArticuloConocimiento,
    CobroSuscripcion,
    DocumentoLegal,
    Plan,
    Suscripcion,
    TicketSoporte,
    VersionCambio,
)

admin.site.register(
    [
        Plan,
        Suscripcion,
        CobroSuscripcion,
        ArticuloConocimiento,
        VersionCambio,
        DocumentoLegal,
        AceptacionLegal,
        TicketSoporte,
    ]
)
