"""
vistas_email.py: Módulo consolidado para el envío de facturas por email.
"""

import json
import logging
import os
import re
import ssl
from configparser import ConfigParser, NoSectionError, NoOptionError
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import formatdate
from email import encoders
import smtplib

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

# Importar modelos y utilidades necesarias
from .models import Factura_D
from apps.home import views_verifactu as vv  # Para generate_factura_pdf

logger = logging.getLogger(__name__)

# Ruta al config.ini
CONFIG_PATH = Path(r"C:\dentfact\config.ini")

def validate_email_address(email: str) -> bool:
    if not email:
        return False
    try:
        validate_email(email)
        return True
    except ValidationError:
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if re.match(pattern, email):
            return True
        logger.warning(f"[EMAIL] Email inválido: {email}")
        return False

class SecureEmailConfig:
    """
    Clase unificada para gestionar configuración SMTP segura.
    Prioridad: Variables de entorno > config.ini > defaults.
    """

    def __init__(self):
        self.host = self._get_config('EMAIL_HOST', 'smtp', 'email_host', 'smtp.gmail.com')
        self.port = int(self._get_config('EMAIL_PORT', 'smtp', 'email_port', '465'))
        self.user = self._get_config('EMAIL_HOST_USER', 'smtp', 'email_host_user', 'noreply@dentfact.es')
        self.password = self._get_config('EMAIL_HOST_PASSWORD', 'smtp', 'email_host_password', '')
        self.from_email = self._get_config('DEFAULT_FROM_EMAIL', 'smtp', 'email_from', self.user)
        self.use_ssl = self._get_bool('EMAIL_USE_SSL', 'smtp', 'email_use_ssl', True)
        self.use_tls = self._get_bool('EMAIL_USE_TLS', 'smtp', 'email_use_tls', False)
        self.timeout = int(self._get_config('SMTP_TIMEOUT', 'smtp', 'smtp_timeout', '10'))

        # Validación inicial
        if not self.is_valid():
            logger.error(f"[EMAIL] Configuración incompleta: {self.get_error_message()}")

        logger.info(
            f"[EMAIL] Configurado: HOST={self.host}, PORT={self.port}, "
            f"USER={self.user}, SSL={self.use_ssl}, TLS={self.use_tls}"
        )

    def _get_config(self, env_var: str, section: str, key: str, default: str) -> str:
        """Obtiene valor con prioridad env > config.ini > default."""
        env_value = os.getenv(env_var)
        if env_value:
            logger.info(f"[EMAIL] Usando {env_var} de variable de entorno")
            return env_value

        try:
            config = ConfigParser()
            config.read(CONFIG_PATH, encoding='utf-8')
            config_value = config.get(section, key, fallback=default)
            if config_value != default:
                logger.info(f"[EMAIL] Usando {key} de config.ini")
            return config_value
        except (NoSectionError, NoOptionError) as e:
            logger.warning(f"[EMAIL] No encontrado en config.ini: {section}.{key} - {e}")
            return default
        except Exception as e:
            logger.error(f"[EMAIL] Error leyendo config.ini: {e}")
            return default

    def _get_bool(self, env_var: str, section: str, key: str, default: bool) -> bool:
        value = self._get_config(env_var, section, key, str(default).lower())
        return value.lower() in ('true', '1', 'yes')

    def is_valid(self) -> bool:
        """Valida que todos los parámetros requeridos estén configurados."""
        required = [self.host, self.port, self.user, self.password]
        return all(required) if required else False  # Corregido para manejar listas vacías

    def get_error_message(self) -> str:
        """Devuelve mensaje descriptivo de qué falta en la configuración."""
        missing = []
        if not self.host:
            missing.append("EMAIL_HOST")
        if not self.port:
            missing.append("EMAIL_PORT")
        if not self.user:
            missing.append("EMAIL_HOST_USER")
        if not self.password:
            missing.append("EMAIL_HOST_PASSWORD")
        return f"Configuración SMTP incompleta. Faltan: {', '.join(missing)}"

def send_email_with_attachment(
    to_email: str,
    subject: str,
    body: str,
    attachment_content: bytes = None,
    attachment_filename: str = None,
    html_body: str = None,
    content_type: str = 'application/pdf'
) -> tuple[bool, str]:
    """
    Función unificada para enviar email con adjunto opcional.
    """
    config = SecureEmailConfig()

    if not config.is_valid():
        error_msg = config.get_error_message()
        logger.error(f"[EMAIL] ❌ {error_msg}")
        return False, error_msg

    if not validate_email_address(to_email):
        error_msg = f"Email inválido: {to_email}"
        logger.error(f"[EMAIL] ❌ {error_msg}")
        return False, error_msg

    try:
        logger.info(f"[EMAIL] Iniciando conexión a {config.host}:{config.port}")

        msg = MIMEMultipart('alternative')
        msg['From'] = config.from_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg['Date'] = formatdate(localtime=True)

        # Agregar cuerpo (texto y HTML si aplica)
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        if html_body:
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        # Agregar adjunto si se proporciona
        if attachment_content and attachment_filename:
            subtype = content_type.split('/')[-1] if '/' in content_type else 'octet-stream'
            attachment = MIMEApplication(attachment_content, _subtype=subtype)
            attachment.add_header('Content-Disposition', 'attachment', filename=attachment_filename)
            encoders.encode_base64(attachment)
            msg.attach(attachment)
            logger.info(f"[EMAIL] Adjunto agregado: {attachment_filename} ({len(attachment_content)} bytes)")

        # Conexión SMTP
        context = ssl.create_default_context()
        if config.use_ssl:
            server = smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout, context=context)
        else:
            server = smtplib.SMTP(config.host, config.port, timeout=config.timeout)
            if config.use_tls:
                server.starttls(context=context)

        logger.info(f"[EMAIL] ✓ Conectado a {config.host}:{config.port}")

        server.login(config.user, config.password)
        logger.info(f"[EMAIL] ✓ Autenticado como {config.user}")

        server.send_message(msg)
        server.quit()

        logger.info(f"[EMAIL] ✓ Email enviado exitosamente a {to_email}")
        return True, f"Email enviado correctamente a {to_email}"

    except smtplib.SMTPAuthenticationError as e:
        error_msg = "Error de autenticación SMTP: Verifica EMAIL_HOST_USER y EMAIL_HOST_PASSWORD"
        logger.error(f"[EMAIL] ❌ {error_msg}: {e}")
        return False, error_msg

    except smtplib.SMTPServerDisconnected as e:
        error_msg = "Servidor SMTP desconectado. Verifica EMAIL_HOST y EMAIL_PORT"
        logger.error(f"[EMAIL] ❌ {error_msg}: {e}")
        return False, error_msg

    except smtplib.SMTPException as e:
        error_msg = f"Error SMTP general: {str(e)}"
        logger.error(f"[EMAIL] ❌ {error_msg}")
        return False, error_msg

    except TimeoutError as e:
        error_msg = "Timeout al conectar con servidor SMTP. Verifica conexión a internet"
        logger.error(f"[EMAIL] ❌ {error_msg}: {e}")
        return False, error_msg

    except Exception as e:
        error_msg = f"Error inesperado enviando email: {str(e)}"
        logger.error(f"[EMAIL] ❌ {error_msg}", exc_info=True)
        return False, error_msg

@csrf_exempt
@require_http_methods(["POST"])
@login_required
def send_factura_consolidated(request, factura_id: str):
    """
    Vista consolidada para enviar factura por email.
    """
    try:
        # Parsear request (JSON o POST)
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            to_email = data.get('email')
            factura_id = data.get('facturaId', factura_id)
        else:
            data = request.POST
            to_email = data.get('to_email')
            factura_id = data.get('facturaId', factura_id)

        logger.info(f"[SEND_FACTURA] Procesando factura: {factura_id}")

        # Obtener factura
        try:
            factura = Factura_D.objects.get(FACTURA=factura_id)
        except Factura_D.DoesNotExist:
            error_msg = f"Factura no encontrada: {factura_id}"
            logger.error(f"[SEND_FACTURA] ❌ {error_msg}")
            return JsonResponse({'status': 'error', 'message': error_msg}, status=404)

        # Usar email de factura si no se proporciona
        to_email = to_email or factura.EMAIL
        if not to_email or not validate_email_address(to_email):
            error_msg = f"Email inválido: {to_email}"
            logger.error(f"[SEND_FACTURA] ❌ {error_msg}")
            return JsonResponse({'status': 'error', 'message': error_msg}, status=400)

        logger.info(f"[SEND_FACTURA] Email destino: {to_email}")

        # Generar PDF (usando función de views_verifactu)
        try:
            pdf_content = vv.generate_factura_pdf(factura)
            logger.info(f"[SEND_FACTURA] PDF generado: {len(pdf_content)} bytes")
        except Exception as e:
            error_msg = f"Error generando PDF: {str(e)}"
            logger.error(f"[SEND_FACTURA] ❌ {error_msg}")
            return JsonResponse({'status': 'error', 'message': error_msg}, status=500)

        # Preparar email (corregido f-string)
        subject = f"Factura {factura_id}"
        body = f"Adjunto factura {factura_id}\n\nEmitida: {factura.EMISION}\n\nPor favor, no responda a este correo."  # Removido 'or factura.fecha' asumiendo no existe

        success, message = send_email_with_attachment(
            to_email=to_email,
            subject=subject,
            body=body,
            attachment_content=pdf_content,
            attachment_filename=f"Factura_{factura_id}.pdf",
        )

        if success:
            logger.info(f"[SEND_FACTURA] ✓ Email enviado exitosamente a {to_email}")
            return JsonResponse({'status': 'success', 'message': message})
        else:
            logger.error(f"[SEND_FACTURA] ❌ Error: {message}")
            return JsonResponse({'status': 'error', 'message': message}, status=500)

    except json.JSONDecodeError as e:
        error_msg = "JSON inválido en request"
        logger.error(f"[SEND_FACTURA] ❌ {error_msg}: {e}")
        return JsonResponse({'status': 'error', 'message': error_msg}, status=400)

    except Exception as e:
        error_msg = f"Error inesperado: {str(e)}"
        logger.error(f"[SEND_FACTURA] ❌ {error_msg}", exc_info=True)
        return JsonResponse({'status': 'error', 'message': error_msg}, status=500)
    
from dotenv import load_dotenv
load_dotenv('c:\dentfact\.env')  # Carga .env

import smtplib
import ssl
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import formatdate
import io

# ================================
# CONFIGURACIÓN DESDE .env
# ================================
config = {
    "host": os.getenv("EMAIL_HOST", "smtp.gmail.com"),
    "port": int(os.getenv("EMAIL_PORT", "587")),
    "use_ssl": os.getenv("EMAIL_USE_SSL", "false").lower() == "true",
    "use_tls": os.getenv("EMAIL_USE_TLS", "true").lower() == "true",
    "user": os.getenv("EMAIL_HOST_USER", ""),
    "password": os.getenv("EMAIL_HOST_PASSWORD", ""),
    "from_email": os.getenv("DEFAULT_FROM_EMAIL", ""),
    "to_email": "cyberaxiom@gmail.com",  # ← TU EMAIL
    "timeout": 30
}

# ================================
# PDF DE PRUEBA (PEQUEÑO)
# ================================
def create_test_pdf():
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        c.drawString(100, 800, "PRUEBA SMTP - ÉXITO")
        c.save()
        buffer.seek(0)
        print(f"[PDF] Generado: {len(buffer.getvalue())/1024:.2f} KB")
        return buffer.getvalue()
    except ImportError:
        print("[PDF] reportlab no instalado → usando texto")
        return b"Prueba sin PDF"

# ================================
# ENVÍO DE EMAIL
# ================================
def send_test_email():
    if not config["password"]:
        print("ERROR: FALTA EMAIL_HOST_PASSWORD en .env")
        return False

    pdf = create_test_pdf()
    msg = MIMEMultipart()
    msg['From'] = config["from_email"]
    msg['To'] = config["to_email"]
    msg['Subject'] = "PRUEBA SMTP - DentFact"
    msg.attach(MIMEText("Email de prueba desde script independiente.", 'plain'))

    # Adjuntar PDF
    att = MIMEApplication(pdf, _subtype="pdf")
    att.add_header('Content-Disposition', 'attachment', filename="prueba.pdf")
    msg.attach(att)

    context = ssl.create_default_context()
    try:
        print(f"[SMTP] Conectando a {config['host']}:{config['port']}...")
        if config["use_ssl"]:
            server = smtplib.SMTP_SSL(config["host"], config["port"], timeout=config["timeout"], context=context)
        else:
            server = smtplib.SMTP(config["host"], config["port"], timeout=config["timeout"])
            if config["use_tls"]:
                print("[SMTP] Iniciando TLS...")
                server.starttls(context=context)
        print("[SMTP] Autenticando...")
        server.login(config["user"], config["password"])
        print(f"[SMTP] Enviando a {config['to_email']}...")
        server.send_message(msg)
        server.quit()
        print("EMAIL ENVIADO CORRECTAMENTE")
        return True
    except Exception as e:
        print(f"ERROR SMTP: {e}")
        return False