"""Cliente de los servicios web de ARCA (ex AFIP): WSAA (autenticación) y WSFEv1 (factura electrónica).

Modos (settings.ARCA_MODO):
- "simulado": no se conecta; devuelve CAE ficticios. Sin validez fiscal (solo desarrollo y demo).
- "homologacion": servicios de prueba de ARCA. Requiere certificado de homologación.
- "produccion": servicios reales.
"""

import base64
import logging
import random
from datetime import datetime, timedelta
from decimal import Decimal

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7
from django.conf import settings
from django.utils import timezone
from lxml import etree

logger = logging.getLogger(__name__)

URLS = {
    "homologacion": {
        "wsaa": "https://wsaahomo.afip.gov.ar/ws/services/LoginCms",
        "wsfe": "https://wswhomo.afip.gov.ar/wsfev1/service.asmx",
    },
    "produccion": {
        "wsaa": "https://wsaa.afip.gov.ar/ws/services/LoginCms",
        "wsfe": "https://servicios1.afip.gov.ar/wsfev1/service.asmx",
    },
}
NS_FE = "http://ar.gov.afip.dif.FEV1/"
TIMEOUT = 30

ALICUOTAS_ID = {
    Decimal("0"): 3,
    Decimal("10.5"): 4,
    Decimal("21"): 5,
    Decimal("27"): 6,
    Decimal("5"): 8,
    Decimal("2.5"): 9,
}


class ArcaError(Exception):
    """Error de comunicación (reintentable): ARCA no respondió o respondió con error de servicio."""


class ArcaRechazo(Exception):
    """ARCA procesó el pedido y rechazó el comprobante (no reintentable sin corregir)."""


def _fmt_fecha(fecha):
    return fecha.strftime("%Y%m%d")


def _parse_fecha(texto):
    return datetime.strptime(texto, "%Y%m%d").date() if texto else None


class ClienteSimulado:
    modo = "simulado"

    def __init__(self, cuit):
        self.cuit = cuit

    def ultimo_autorizado(self, punto_venta, tipo):
        from .models import Factura

        ultimo = (
            Factura.objects.filter(punto_venta__numero=punto_venta, tipo=tipo, numero__isnull=False, simulada=True)
            .order_by("-numero")
            .values_list("numero", flat=True)
            .first()
        )
        return ultimo or 0

    def solicitar_cae(self, datos):
        cae = "7" + "".join(random.choice("0123456789") for _ in range(13))
        return {"cae": cae, "vencimiento": timezone.localdate() + timedelta(days=10), "observaciones": "SIMULADO"}


class ClienteARCA:
    def __init__(self, cuit, cert_path, key_path, modo):
        if modo not in URLS:
            raise ValueError(f"Modo ARCA desconocido: {modo}")
        self.cuit = str(cuit).replace("-", "")
        self.cert_path = cert_path
        self.key_path = key_path
        self.modo = modo
        self.urls = URLS[modo]

    # --- WSAA ---
    def _tra(self, servicio):
        ahora = timezone.now()
        return (
            '<?xml version="1.0" encoding="UTF-8"?><loginTicketRequest version="1.0"><header>'
            f"<uniqueId>{int(ahora.timestamp())}</uniqueId>"
            f"<generationTime>{(ahora - timedelta(minutes=10)).isoformat()}</generationTime>"
            f"<expirationTime>{(ahora + timedelta(minutes=10)).isoformat()}</expirationTime>"
            f"</header><service>{servicio}</service></loginTicketRequest>"
        ).encode()

    def _firmar(self, contenido):
        with open(self.cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        with open(self.key_path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        cms = (
            pkcs7.PKCS7SignatureBuilder()
            .set_data(contenido)
            .add_signer(cert, key, hashes.SHA256())
            .sign(serialization.Encoding.DER, [])
        )
        return base64.b64encode(cms).decode()

    def ticket(self, servicio="wsfe"):
        from .models import TicketAcceso

        vigente = TicketAcceso.objects.filter(
            cuit=self.cuit, servicio=servicio, modo=self.modo, expiracion__gt=timezone.now() + timedelta(minutes=5)
        ).first()
        if vigente:
            return vigente.token, vigente.sign
        cms = self._firmar(self._tra(servicio))
        sobre = (
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:wsaa="http://wsaa.view.sua.dvadac.desein.afip.gov"><soapenv:Header/><soapenv:Body>'
            f"<wsaa:loginCms><wsaa:in0>{cms}</wsaa:in0></wsaa:loginCms></soapenv:Body></soapenv:Envelope>"
        )
        try:
            resp = requests.post(
                self.urls["wsaa"],
                data=sobre.encode(),
                timeout=TIMEOUT,
                headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
            )
        except requests.RequestException as exc:
            raise ArcaError(f"WSAA no responde: {exc}") from exc
        arbol = etree.fromstring(resp.content)
        ret = arbol.find(".//{*}loginCmsReturn")
        if ret is None:
            falla = arbol.find(".//faultstring")
            raise ArcaError(f"WSAA rechazó el pedido: {falla.text if falla is not None else resp.text[:300]}")
        ticket = etree.fromstring(ret.text.encode())
        token = ticket.findtext(".//token")
        sign = ticket.findtext(".//sign")
        expiracion = datetime.fromisoformat(ticket.findtext(".//expirationTime"))
        TicketAcceso.objects.create(
            cuit=self.cuit, servicio=servicio, modo=self.modo, token=token, sign=sign, expiracion=expiracion
        )
        return token, sign

    # --- WSFEv1 ---
    def _llamar(self, metodo, cuerpo):
        token, sign = self.ticket()
        auth = f"<ar:Auth><ar:Token>{token}</ar:Token><ar:Sign>{sign}</ar:Sign><ar:Cuit>{self.cuit}</ar:Cuit></ar:Auth>"
        sobre = (
            f'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ar="{NS_FE}">'
            f"<soapenv:Header/><soapenv:Body><ar:{metodo}>{auth}{cuerpo}</ar:{metodo}></soapenv:Body>"
            "</soapenv:Envelope>"
        )
        try:
            resp = requests.post(
                self.urls["wsfe"],
                data=sobre.encode(),
                timeout=TIMEOUT,
                headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": NS_FE + metodo},
            )
        except requests.RequestException as exc:
            raise ArcaError(f"WSFEv1 no responde: {exc}") from exc
        if resp.status_code >= 500 and b"Fault" not in resp.content:
            raise ArcaError(f"WSFEv1 error HTTP {resp.status_code}")
        arbol = etree.fromstring(resp.content)
        errores = [f"{e.findtext('{*}Code')}: {e.findtext('{*}Msg')}" for e in arbol.iterfind(".//{*}Errors/{*}Err")]
        return arbol, errores

    def ultimo_autorizado(self, punto_venta, tipo):
        arbol, errores = self._llamar(
            "FECompUltimoAutorizado", f"<ar:PtoVta>{punto_venta}</ar:PtoVta><ar:CbteTipo>{tipo}</ar:CbteTipo>"
        )
        if errores:
            raise ArcaError("; ".join(errores))
        return int(arbol.findtext(".//{*}CbteNro") or 0)

    def solicitar_cae(self, d):
        """d: dict con los datos del comprobante (ver services._datos_arca)."""
        iva = ""
        if d["alicuotas"]:
            iva = (
                "<ar:Iva>"
                + "".join(
                    f"<ar:AlicIva><ar:Id>{ALICUOTAS_ID[a['alicuota']]}</ar:Id><ar:BaseImp>{a['base']:.2f}</ar:BaseImp>"
                    f"<ar:Importe>{a['importe']:.2f}</ar:Importe></ar:AlicIva>"
                    for a in d["alicuotas"]
                )
                + "</ar:Iva>"
            )
        asociados = ""
        if d.get("asociado"):
            a = d["asociado"]
            asociados = (
                f"<ar:CbtesAsoc><ar:CbteAsoc><ar:Tipo>{a['tipo']}</ar:Tipo><ar:PtoVta>{a['punto_venta']}"
                f"</ar:PtoVta><ar:Nro>{a['numero']}</ar:Nro><ar:Cuit>{self.cuit}</ar:Cuit>"
                f"<ar:CbteFch>{_fmt_fecha(a['fecha'])}</ar:CbteFch></ar:CbteAsoc></ar:CbtesAsoc>"
            )
        servicio = ""
        if d["concepto"] in (2, 3):
            servicio = (
                f"<ar:FchServDesde>{_fmt_fecha(d['servicio_desde'])}</ar:FchServDesde>"
                f"<ar:FchServHasta>{_fmt_fecha(d['servicio_hasta'])}</ar:FchServHasta>"
                f"<ar:FchVtoPago>{_fmt_fecha(d['vencimiento_pago'])}</ar:FchVtoPago>"
            )
        cuerpo = (
            f"<ar:FeCAEReq><ar:FeCabReq><ar:CantReg>1</ar:CantReg><ar:PtoVta>{d['punto_venta']}</ar:PtoVta>"
            f"<ar:CbteTipo>{d['tipo']}</ar:CbteTipo></ar:FeCabReq><ar:FeDetReq><ar:FECAEDetRequest>"
            f"<ar:Concepto>{d['concepto']}</ar:Concepto><ar:DocTipo>{d['doc_tipo']}</ar:DocTipo>"
            f"<ar:DocNro>{d['doc_nro']}</ar:DocNro><ar:CbteDesde>{d['numero']}</ar:CbteDesde>"
            f"<ar:CbteHasta>{d['numero']}</ar:CbteHasta><ar:CbteFch>{_fmt_fecha(d['fecha'])}</ar:CbteFch>"
            f"<ar:ImpTotal>{d['total']:.2f}</ar:ImpTotal><ar:ImpTotConc>0.00</ar:ImpTotConc>"
            f"<ar:ImpNeto>{d['neto']:.2f}</ar:ImpNeto><ar:ImpOpEx>{d['exento']:.2f}</ar:ImpOpEx>"
            f"<ar:ImpTrib>0.00</ar:ImpTrib><ar:ImpIVA>{d['iva']:.2f}</ar:ImpIVA>{servicio}"
            f"<ar:MonId>{d['moneda']}</ar:MonId><ar:MonCotiz>{d['cotizacion']}</ar:MonCotiz>"
            f"<ar:CondicionIVAReceptorId>{d['condicion_iva_receptor']}</ar:CondicionIVAReceptorId>"
            f"{asociados}{iva}</ar:FECAEDetRequest></ar:FeDetReq></ar:FeCAEReq>"
        )
        arbol, errores = self._llamar("FECAESolicitar", cuerpo)
        resultado = arbol.findtext(".//{*}FECAEDetResponse/{*}Resultado")
        obs = [f"{o.findtext('{*}Code')}: {o.findtext('{*}Msg')}" for o in arbol.iterfind(".//{*}Obs/{*}Obs")]
        if resultado == "A":
            return {
                "cae": arbol.findtext(".//{*}CAE"),
                "vencimiento": _parse_fecha(arbol.findtext(".//{*}CAEFchVto")),
                "observaciones": "; ".join(obs),
            }
        if resultado == "R":
            raise ArcaRechazo("; ".join(errores + obs) or "Comprobante rechazado por ARCA")
        raise ArcaError("; ".join(errores) or "Respuesta inesperada de WSFEv1")


def cliente(hotel=None):
    modo = settings.ARCA_MODO
    cuit = (settings.ARCA_CUIT or (hotel.cuit if hotel else "")).replace("-", "")
    if modo == "simulado":
        return ClienteSimulado(cuit)
    if not (settings.ARCA_CERT and settings.ARCA_KEY):
        raise ArcaError("Falta configurar ARCA_CERT y ARCA_KEY para conectarse a ARCA.")
    return ClienteARCA(cuit, settings.ARCA_CERT, settings.ARCA_KEY, modo)
