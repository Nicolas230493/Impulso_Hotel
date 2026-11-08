from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Notificacion


@login_required
def lista(request):
    qs = Notificacion.objects.filter(usuario=request.user, canal=Notificacion.Canal.INTERNA)
    pagina = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "notificaciones/lista.html", {"page_obj": pagina})


@login_required
def campana(request):
    no_leidas = Notificacion.objects.filter(usuario=request.user, leida=False, canal="interna").count()
    return render(request, "notificaciones/_campana.html", {"notificaciones_no_leidas": no_leidas})


@login_required
def abrir(request, pk):
    n = get_object_or_404(Notificacion, pk=pk, usuario=request.user)
    n.leida = True
    n.save(update_fields=["leida", "actualizado_en"])
    if n.url and url_has_allowed_host_and_scheme(n.url, allowed_hosts={request.get_host()}):
        return redirect(n.url)
    return redirect("notificacion_lista")


@login_required
@require_POST
def marcar_todas(request):
    Notificacion.objects.filter(usuario=request.user, leida=False).update(leida=True)
    return redirect("notificacion_lista")
