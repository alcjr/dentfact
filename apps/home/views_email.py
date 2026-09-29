"""
views_email.py: Módulo consolidado para el envío de facturas por email.

Flujo:
  - La cuenta SMTP emisora (From) se resuelve por la clase SecureEmailConfig,
    que lee con prioridad: variables de entorno > config.ini > defaults.
  - El destinatario (To) es el correo del emisor de la factura, es decir
    `factura.EMAIL` — el email del doctor que aparece en la propia factura.
    Se puede sobrescribir puntualmente pasando `email` en el JSON o
    `to_email` en el form, pero el comportamiento por defecto es enviarlo
    al doctor.
  - El PDF adjunto puede venir del cliente (`pdfBase64`) o generarse en
    servidor con ReportLab (`vv.generate_factura_pdf`) si el cliente no
    lo envía.
"""

import base64
import json
import logging
import os
import re
import smtplib
import ssl
from configparser import ConfigParser, NoSectionError, NoOptionError
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .models import Factura_D
from apps.home import views_verifactu as vv


logger = logging.getLogger(__name__)


# =============================================================================
#  Carga opcional de .env
# =============================================================================
try:
    from dotenv import load_dotenv  # type: ignore
    _DOTENV_PATH = Path(settings.BASE_DIR) / '.env'
    if _DOTENV_PATH.exists():
        load_dotenv(_DOTENV_PATH)
        logger.info('[EMAIL] .env cargado desde %s', _DOTENV_PATH)
except ImportError:
    pass
except Exception as e:
    logger.warning('[EMAIL] No se pudo cargar .env: %s', e)


# =============================================================================
#  Excepciones propias
# =============================================================================
class EmailConfigError(Exception):
    """La configuración SMTP está incompleta o es inválida."""


class EmailSendError(Exception):
    """Fallo al enviar un email por SMTP."""


# =============================================================================
#  Validación de email
# =============================================================================
def validate_email_address(email: str) -> bool:
    """
    Valida un email con el validador de Django (más estricto que la regex
    del módulo original). No cae a un regex permisivo en caso de fallo:
    si Django lo rechaza, se rechaza.
    """
    if not email:
        return False
    try:
        validate_email(email)
        return True
    except ValidationError:
        logger.warning('[EMAIL] Email inválido: %r', email)
        return False


# =============================================================================
#  Decodificación del PDF del cliente
# =============================================================================
def _decode_pdf_base64(pdf_base64: str | None) -> bytes | None:
    """
    Convierte un data URI ('data:application/pdf;base64,...') o un base64
    puro a bytes. Devuelve None si está vacío, mal formado, o si el
    resultado no parece un PDF (no empieza por '%PDF-').

    Devuelve None en lugar de lanzar: el llamador decide si usa fallback.
    """
    if not pdf_base64 or not isinstance(pdf_base64, str):
        return None
    try:
        payload = pdf_base64
        if payload.startswith('data:'):
            comma = payload.find(',')
            if comma < 0:
                logger.warning('[PDF] data URI sin coma separadora')
                return None
            payload = payload[comma + 1:]

        # validate=True rechaza caracteres fuera del alfabeto base64
        raw = base64.b64decode(payload, validate=True)
    except Exception as e:
        logger.warning('[PDF] No se pudo decodificar pdfBase64: %s', e)
        return None

    if not raw.startswith(b'%PDF-'):
        logger.warning('[PDF] El payload decodificado no parece un PDF (magic bytes incorrectos)')
        return None

    return raw


# =============================================================================
#  Configuración SMTP (config.ini + variables de entorno)
# =============================================================================
class SecureEmailConfig:
    """
    Configuración SMTP leída con la siguiente prioridad:
        1. Variable de entorno del sistema.
        2. Sección [smtp] de config.ini.
        3. Default del propio código.
    """

    def __init__(self):
        config_path = Path(settings.BASE_DIR) / 'config.ini'
        self._config_path = config_path

        self.host = self._get_config('EMAIL_HOST', 'smtp', 'email_host', 'smtp.gmail.com')
        self.port = int(self._get_config('EMAIL_PORT', 'smtp', 'email_port', '465'))
        self.user = self._get_config('EMAIL_HOST_USER', 'smtp', 'email_host_user', 'noreply@dentfact.es')
        self.password = self._get_config('EMAIL_HOST_PASSWORD', 'smtp', 'email_host_password', '')
        self.from_email = self._get_config('DEFAULT_FROM_EMAIL', 'smtp', 'email_from', self.user)
        self.use_ssl = self._get_bool('EMAIL_USE_SSL', 'smtp', 'email_use_ssl', True)
        self.use_tls = self._get_bool('EMAIL_USE_TLS', 'smtp', 'email_use_tls', False)
        self.timeout = int(self._get_config('SMTP_TIMEOUT', 'smtp', 'smtp_timeout', '10'))

        if not self.is_valid():
            logger.error('[EMAIL] Configuración incompleta: %s', self.get_error_message())

        logger.info(
            '[EMAIL] Configurado: HOST=%s, PORT=%s, USER=%s, SSL=%s, TLS=%s',
            self.host, self.port, self.user, self.use_ssl, self.use_tls,
        )

    def _get_config(self, env_var: str, section: str, key: str, default: str) -> str:
        env_value = os.getenv(env_var)
        if env_value:
            logger.debug('[EMAIL] %s leído de variable de entorno', env_var)
            return env_value

        if not self._config_path.exists():
            logger.warning('[EMAIL] config.ini no encontrado en %s', self._config_path)
            return default

        try:
            config = ConfigParser()
            config.read(self._config_path, encoding='utf-8')
            config_value = config.get(section, key, fallback=default)
            if config_value != default:
                logger.debug('[EMAIL] %s.%s leído de config.ini', section, key)
            return config_value
        except (NoSectionError, NoOptionError) as e:
            logger.warning('[EMAIL] No encontrado en config.ini: %s.%s — %s', section, key, e)
            return default
        except Exception as e:
            logger.error('[EMAIL] Error leyendo config.ini: %s', e)
            return default

    def _get_bool(self, env_var: str, section: str, key: str, default: bool) -> bool:
        value = self._get_config(env_var, section, key, str(default).lower())
        return value.lower() in ('true', '1', 'yes', 'on')

    def is_valid(self) -> bool:
        return bool(self.host and self.port and self.user and self.password)

    def get_error_message(self) -> str:
        missing = []
        if not self.host:     missing.append('EMAIL_HOST')
        if not self.port:     missing.append('EMAIL_PORT')
        if not self.user:     missing.append('EMAIL_HOST_USER')
        if not self.password: missing.append('EMAIL_HOST_PASSWORD')
        return f'Configuración SMTP incompleta. Faltan: {", ".join(missing)}'


# =============================================================================
#  Envío de email con adjunto
# =============================================================================
def send_email_with_attachment(
    to_email: str,
    subject: str,
    body: str,
    attachment_content: bytes = None,
    attachment_filename: str = None,
    html_body: str = None,
    content_type: str = 'application/pdf',
    reply_to: str = None,
) -> tuple[bool, str]:
    """
    Envía un email con cuerpo de texto, cuerpo HTML opcional y adjunto
    opcional. Devuelve (éxito, mensaje).

    Estructura MIME:
        multipart/mixed
        ├── multipart/alternative
        │   ├── text/plain
        │   └── text/html
        └── application/pdf (adjunto)
    """
    config = SecureEmailConfig()

    if not config.is_valid():
        error_msg = config.get_error_message()
        logger.error('[EMAIL] %s', error_msg)
        return False, error_msg

    if not validate_email_address(to_email):
        error_msg = f'Email inválido: {to_email!r}'
        logger.error('[EMAIL] %s', error_msg)
        return False, error_msg

    try:
        logger.info('[EMAIL] Iniciando conexión a %s:%s', config.host, config.port)

        msg = EmailMessage()
        msg['From'] = config.from_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg['Reply-To'] = reply_to or config.from_email
        msg['Message-ID'] = make_msgid(
            domain=getattr(settings, 'MESSAGE_ID_DOMAIN', None) or config.host,
        )
        msg['Auto-Submitted'] = 'auto-generated'
        msg['X-Auto-Response-Suppress'] = 'All'

        msg.set_content(body, charset='utf-8')
        if html_body:
            msg.add_alternative(html_body, subtype='html')

        if attachment_content and attachment_filename:
            maintype, _, subtype = content_type.partition('/')
            msg.add_attachment(
                attachment_content,
                maintype=maintype or 'application',
                subtype=subtype or 'octet-stream',
                filename=attachment_filename,
            )
            logger.info(
                '[EMAIL] Adjunto agregado: %s (%d bytes)',
                attachment_filename, len(attachment_content),
            )

        context = ssl.create_default_context()

        if config.use_ssl:
            server = smtplib.SMTP_SSL(
                config.host, config.port, timeout=config.timeout, context=context,
            )
        else:
            server = smtplib.SMTP(
                config.host, config.port, timeout=config.timeout,
            )
            if config.use_tls:
                server.starttls(context=context)

        try:
            logger.info('[EMAIL] Conectado a %s:%s', config.host, config.port)
            server.login(config.user, config.password)
            logger.info('[EMAIL] Autenticado como %s', config.user)
            server.send_message(msg)
            logger.info('[EMAIL] Email enviado correctamente a %s', to_email)
        finally:
            try:
                server.quit()
            except Exception:
                pass

        return True, f'Email enviado correctamente a {to_email}'

    except smtplib.SMTPAuthenticationError as e:
        error_msg = 'Error de autenticación SMTP: Verifica EMAIL_HOST_USER y EMAIL_HOST_PASSWORD'
        logger.error('[EMAIL] %s: %s', error_msg, e)
        return False, error_msg

    except smtplib.SMTPServerDisconnected as e:
        error_msg = 'Servidor SMTP desconectado. Verifica EMAIL_HOST y EMAIL_PORT'
        logger.error('[EMAIL] %s: %s', error_msg, e)
        return False, error_msg

    except smtplib.SMTPException as e:
        error_msg = f'Error SMTP general: {e}'
        logger.error('[EMAIL] %s', error_msg)
        return False, error_msg

    except TimeoutError as e:
        error_msg = 'Timeout al conectar con servidor SMTP. Verifica conexión a internet'
        logger.error('[EMAIL] %s: %s', error_msg, e)
        return False, error_msg

    except Exception as e:
        error_msg = f'Error inesperado enviando email: {e}'
        logger.exception('[EMAIL] %s', error_msg)
        return False, error_msg


# =============================================================================
#  Cuerpo HTML del correo
# =============================================================================
def _build_factura_html_body(factura) -> str:
    doctor = factura.DOCTOR or 'doctor/a'
    return f"""\
<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"></head>
<body style="font-family: Arial, Helvetica, sans-serif; color:#0f172a; line-height:1.5; font-size:14px;">
  <p>Estimado/a <strong>{doctor}</strong>,</p>

  <p>Adjuntamos la factura <strong>{factura.FACTURA}</strong>
     correspondiente al periodo
     <strong>{factura.L_DESDE} — {factura.L_HASTA}</strong>.</p>

  <table style="border-collapse:collapse; margin:16px 0;">
    <tr>
      <td style="padding:4px 12px 4px 0;"><strong>Nº Factura:</strong></td>
      <td>{factura.FACTURA}</td>
    </tr>
    <tr>
      <td style="padding:4px 12px 4px 0;"><strong>Emisión:</strong></td>
      <td>{factura.EMISION}</td>
    </tr>
    <tr>
      <td style="padding:4px 12px 4px 0;"><strong>Total:</strong></td>
      <td>{factura.TOTAL_FACTURA}</td>
    </tr>
  </table>

  <p style="font-size:12px; color:#64748b;">
    Por favor, no responda directamente a este correo.
  </p>

  <p style="font-size:12px; color:#64748b;">
    DENTFACT — Gestión odontológica
  </p>
</body>
</html>
"""


def _build_factura_text_body(factura) -> str:
    doctor = factura.DOCTOR or 'doctor/a'
    return (
        f'Estimado/a {doctor},\n\n'
        f'Adjuntamos la factura {factura.FACTURA} correspondiente al '
        f'periodo {factura.L_DESDE} — {factura.L_HASTA}.\n\n'
        f'Nº Factura : {factura.FACTURA}\n'
        f'Emisión    : {factura.EMISION}\n'
        f'Total      : {factura.TOTAL_FACTURA}\n\n'
        f'Por favor, no responda directamente a este correo.\n\n'
        f'DENTFACT — Gestión odontológica\n'
    )


# =============================================================================
#  Vista: enviar factura por email
# =============================================================================
@require_http_methods(['POST'])
@login_required
def send_factura_consolidated(request, factura_id: str):
    """
    Envía la factura por email.

    El PDF adjunto puede venir de dos fuentes:
      1. El cliente (html2pdf) lo envía en `pdfBase64` → se usa tal cual.
         Es la vía preferente porque produce el MISMO PDF que "Guardar".
      2. Si no viene (o viene malformado), el servidor lo genera con
         `vv.generate_factura_pdf` (ReportLab) como fallback.

    Destinatario por defecto: `factura.EMAIL` (el doctor emisor).
    """
    try:
        # ---- 1. Parsear request -------------------------------------------
        pdf_base64 = None

        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body or b'{}')
            except json.JSONDecodeError as e:
                logger.error('[SEND_FACTURA] JSON inválido: %s', e)
                return JsonResponse(
                    {'status': 'error', 'message': 'JSON inválido en la petición'},
                    status=400,
                )
            to_email_override = data.get('email')
            pdf_base64 = data.get('pdfBase64')
            factura_id = data.get('facturaId', factura_id)
        else:
            to_email_override = request.POST.get('to_email')
            pdf_base64 = request.POST.get('pdfBase64')
            factura_id = request.POST.get('facturaId', factura_id)

        logger.info('[SEND_FACTURA] Procesando factura: %s', factura_id)

        # ---- 2. Obtener factura ------------------------------------------
        try:
            factura = Factura_D.objects.get(FACTURA=factura_id)
        except Factura_D.DoesNotExist:
            logger.error('[SEND_FACTURA] Factura no encontrada: %s', factura_id)
            return JsonResponse(
                {'status': 'error', 'message': f'Factura no encontrada: {factura_id}'},
                status=404,
            )

        # ---- 3. Destinatario ---------------------------------------------
        to_email = to_email_override or factura.EMAIL

        if not validate_email_address(to_email):
            logger.error(
                '[SEND_FACTURA] Email inválido o ausente: %r (override=%r, factura.EMAIL=%r)',
                to_email, to_email_override, getattr(factura, 'EMAIL', None),
            )
            return JsonResponse(
                {'status': 'error',
                 'message': f'El correo del emisor no es válido o no está definido: {to_email!r}'},
                status=400,
            )

        logger.info('[SEND_FACTURA] Destinatario: %s', to_email)

        # ---- 4. Obtener el PDF -------------------------------------------
        # 4a. PDF del cliente (preferente)
        pdf_content = None
        if pdf_base64:
            pdf_content = _decode_pdf_base64(pdf_base64)
            if pdf_content:
                logger.info(
                    '[SEND_FACTURA] PDF del cliente aceptado: %d bytes (%.1f KB)',
                    len(pdf_content), len(pdf_content) / 1024,
                )
            else:
                logger.warning('[SEND_FACTURA] pdfBase64 inválido o corrupto; se usará fallback')

        # 4b. Fallback: generar en servidor
        if not pdf_content:
            try:
                pdf_content = vv.generate_factura_pdf(factura)
                if not pdf_content:
                    raise ValueError('generate_factura_pdf devolvió vacío')
                logger.info('[SEND_FACTURA] PDF generado en servidor: %d bytes', len(pdf_content))
            except Exception as e:
                logger.exception('[SEND_FACTURA] Error generando PDF en servidor')
                return JsonResponse(
                    {'status': 'error', 'message': f'Error generando PDF: {e}'},
                    status=500,
                )

        # ---- 5. Construir y enviar el correo -----------------------------
        subject = f'[DENTFACT] Factura {factura.FACTURA} — {factura.EMISION}'
        body_text = _build_factura_text_body(factura)
        body_html = _build_factura_html_body(factura)
        reply_to = getattr(settings, 'FACTURAS_REPLY_TO', None)

        success, message = send_email_with_attachment(
            to_email=to_email,
            subject=subject,
            body=body_text,
            html_body=body_html,
            attachment_content=pdf_content,
            attachment_filename=f'Factura_{factura.FACTURA}.pdf',
            content_type='application/pdf',
            reply_to=reply_to,
        )

        if success:
            logger.info('[SEND_FACTURA] Enviada %s a %s', factura.FACTURA, to_email)
            return JsonResponse({'status': 'success', 'message': message})
        else:
            logger.error('[SEND_FACTURA] Fallo: %s', message)
            return JsonResponse(
                {'status': 'error', 'message': message},
                status=500,
            )

    except json.JSONDecodeError as e:
        logger.error('[SEND_FACTURA] JSON inválido: %s', e)
        return JsonResponse(
            {'status': 'error', 'message': 'JSON inválido en request'},
            status=400,
        )
    except Exception as e:
        logger.exception('[SEND_FACTURA] Error inesperado')
        return JsonResponse(
            {'status': 'error', 'message': f'Error inesperado: {e}'},
            status=500,
        )