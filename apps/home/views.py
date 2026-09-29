import os
import json
import logging
import sqlite3
import pandas as pd
import chardet
import locale
from configparser import ConfigParser
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
from collections import deque
import re

from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.db import connection, transaction
from django.http import HttpResponse, JsonResponse, HttpResponseNotFound, FileResponse
from django.template import loader, TemplateDoesNotExist
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.template.response import TemplateResponse


from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated

from .models import (
    Importes, Factura_R, Factura_C, Factura_D, Factura_V,
    Doctor, Docpercent, Centro, Sociedad, Especialidad
)
from .serializers import (
    DoctorSerializer, DocpercentSerializer, CentroSerializer,
    EmpresaSerializer, EspecialidadSerializer, ImportesSerializer,
    Factura_RSerializer, Factura_CSerializer, Factura_DSerializer, Factura_VSerializer
)

from apps.home import views_pdf as vp
from apps.home import views_factura as vf
from apps.home import views_dashboard as vd
from apps.home import views_verifactu as vv
from apps.home import views_utils as vu

# Inicialización de logging y locale
locale.setlocale(locale.LC_ALL, 'es_ES.UTF-8')
logger = logging.getLogger(__name__)

CONFIG_FILE = Path('c:/dentfact/config.ini')

try:
    config = ConfigParser()
    config.read(CONFIG_FILE, encoding='utf-8')
    pdf = config.get('inputs', 'pdf')
    tablas = config.get('inputs', 'tablas')
    master = config.get('inputs', 'master')
    logs = config.get('outputs', 'logs')
    facturas = config.get('outputs', 'facturas')
    sqlite3_dbpath = config.get('outputs', 'sqlite3_dbpath')
    vGP = config.getfloat('default', 'GABINETE_PERCENTAGE', fallback=0.115)
    vIVA = config.getfloat('default', 'IVA_PERCENTAGE', fallback=0.21)
    vIRPF = config.getfloat('default', 'IRPF_PERCENTAGE', fallback=0.15)
    vDD = config.getint('default', 'DD_FEMISION', fallback=5)
    vGASTOS = config.getfloat('default', 'GASTOS', fallback=50)
    vPath = Path(r'c:\data\exports')
except Exception as e:
    logger.critical(f"Error al leer el archivo de configuración {CONFIG_FILE}: {e}", exc_info=True)
    raise



@login_required(login_url='/auth/login/')

def init_dashboard(request):
    """
    Punto de entrada para el dashboard.
    Redirige toda la lógica a `dashboard()`.
    """
    return vd.dashboard(request)


@login_required(login_url='/auth/login/')
def init_factura(request):
    """Vista para inicializar el procesamiento de facturas."""
    success = vf.init_factura(), vv.init_verifactu()
    if success:
        messages.success(request, "Inicialización de facturas completada con éxito")
        return HttpResponse("Inicialización completada con éxito")
    messages.error(request, "Error al inicializar facturas")
    return HttpResponse("Error al inicializar", status=500)

@login_required(login_url='/auth/login/')
def updFactura_C(request):
    """Vista para actualizar facturas en factura_c."""
    try:
        success = vf.init_factura()  # Corregido de init_app_factura a init_factura
        if success:
            messages.success(request, "Actualización de facturas completada con éxito")
            return HttpResponse("Actualización completada con éxito")
        messages.error(request, "Error al actualizar facturas")
        return HttpResponse("Error al actualizar", status=500)
    except Exception as e:
        logger.error(f"Error en updFactura_C: {e}", exc_info=True)
        return HttpResponse(f"Error: {str(e)}", status=500)

def initialize_all_apps(request=None):
    """
    Inicializa todas las aplicaciones del sistema:
    PDF, facturación, dashboard y Veri*Factu.
    Devuelve (context, success) -> (dict, bool)
    """
    logger.info("🔄 Iniciando proceso de inicialización global de aplicaciones...")
    context = {}

    try:
        # 1️⃣ Inicialización básica de módulos principales
        vp.init_pdf()
        vf.init_factura()

        # 2️⃣ Inicializar dashboard (solo si hay request)
        if request:
            logger.info("📈 Inicializando módulo Dashboard...")
            init_dashboard(request)

        # 3️⃣ Inicializar Veri*Factu
        vv.init_verifactu()

    except Exception as e:
        logger.exception(f"🔥 Error al inicializar aplicaciones: {e}")
        return {}, False

    logger.info("✅ Todas las aplicaciones inicializadas correctamente.")
    return context, True


# ------------------------------------------
# Autenticación y logs
# ------------------------------------------
def read_log_file_optimized(log_file_path, max_lines=500):
    """
    Lee el archivo de logs de forma optimizada:
    - Lee solo las últimas N líneas
    - Usa lectura inversa para archivos grandes
    - Detecta encoding automáticamente
    """
    logs_list = []
    
    try:
        if not os.path.exists(log_file_path):
            return [], 0, "Archivo no existe"
        
        file_size = os.path.getsize(log_file_path)
        
        # Para archivos pequeños (< 1MB), leer normalmente
        if file_size < 1024 * 1024:
            with open(log_file_path, 'rb') as f:
                raw_data = f.read()
                enc = chardet.detect(raw_data)['encoding'] or 'utf-8'
            
            with open(log_file_path, 'r', encoding=enc) as f:
                lines = f.readlines()
                # Tomar solo las últimas max_lines
                lines = lines[-max_lines:] if len(lines) > max_lines else lines
        else:
            # Para archivos grandes, leer desde el final
            enc = 'utf-8'
            lines = read_last_n_lines(log_file_path, max_lines, enc)
        
        # Parsear las líneas
        for line in lines:
            parsed = parse_log_line(line)
            if parsed:
                logs_list.append(parsed)
        
        return logs_list, file_size, None
    
    except Exception as e:
        logger.error(f"Error al leer archivo de logs: {e}", exc_info=True)
        return [], 0, str(e)


def read_last_n_lines(file_path, n, encoding='utf-8'):
    """
    Lee las últimas N líneas de un archivo de forma eficiente
    sin cargar todo el archivo en memoria.
    """
    lines = deque(maxlen=n)
    
    try:
        with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
            for line in f:
                lines.append(line)
        return list(lines)
    except Exception as e:
        logger.error(f"Error en read_last_n_lines: {e}")
        return []


def parse_log_line(line):
    """
    Parsea una línea del log y extrae: fecha, hora, nivel, módulo, mensaje
    Formato esperado: NIVEL FECHA HORA MODULO MENSAJE
    """
    
    line = line.strip()
    if not line:
        return None
    
    # Patrón: NIVEL FECHA HORA MODULO MENSAJE
    # Ejemplo: INFO 2025-01-26 14:30:45 views.py Mensaje de log
    pattern = r'^(\w+)\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})[,\.]?\d*\s+(\S+)\s+(.*)$'
    match = re.match(pattern, line)
    
    if match:
        nivel, fecha, hora, module, mensaje = match.groups()
        return {
            'nivel': nivel,
            'fecha': fecha,
            'hora': hora,
            'module': module,
            'mensaje': mensaje.strip()
        }
    
    # Formato alternativo: FECHA HORA NIVEL MODULO MENSAJE
    pattern2 = r'^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})[,\.]?\d*\s+(\w+)\s+(\S+)\s+(.*)$'
    match2 = re.match(pattern2, line)
    
    if match2:
        fecha, hora, nivel, module, mensaje = match2.groups()
        return {
            'nivel': nivel,
            'fecha': fecha,
            'hora': hora,
            'module': module,
            'mensaje': mensaje.strip()
        }
    
    # Si no coincide con ningún patrón, devolver como mensaje simple
    return {
        'nivel': 'INFO',
        'fecha': '',
        'hora': '',
        'module': '',
        'mensaje': line
    }


@login_required(login_url='/auth/login/')
def view_logs(request):
    """
    Vista principal del visor de logs.
    Carga inicial con las últimas 500 líneas.
    """
    log_file_path = os.environ.get('LOG_FILE_PATH', r'c:\data\logs\dentfact.log')
    
    # Leer solo las últimas 500 líneas para carga inicial rápida
    logs_list, file_size, error = read_log_file_optimized(log_file_path, max_lines=500)
    
    context = {
        'logs': mark_safe(json.dumps(logs_list, ensure_ascii=False)),
        'log_file_path': log_file_path,
        'log_file_size': file_size,
        'log_line_count': len(logs_list),
        'error': error
    }
    
    return render(request, 'visor.html', context)


@login_required(login_url='/auth/login/')
def load_log_json(request):
    """
    Endpoint AJAX para cargar logs en formato JSON.
    Soporta parámetro 'lines' para limitar cantidad de líneas.
    """
    log_file_path = os.environ.get('LOG_FILE_PATH', r'c:\data\logs\dentfact.log')
    
    # Obtener parámetro de líneas (por defecto 500)
    try:
        max_lines = int(request.GET.get('lines', 500))
        max_lines = min(max_lines, 10000)  # Límite máximo de 10000 líneas
    except ValueError:
        max_lines = 500
    
    logs_list, file_size, error = read_log_file_optimized(log_file_path, max_lines)
    
    if error:
        return JsonResponse({
            'success': False,
            'error': error,
            'logs': [],
            'file_path': log_file_path,
            'file_size': 0,
            'lines': []
        }, status=404 if 'no existe' in error.lower() else 500)
    
    return JsonResponse({
        'success': True,
        'logs': logs_list,
        'file_path': log_file_path,
        'file_size': file_size,
        'lines': logs_list
    })


@login_required(login_url='/auth/login/')
def download_log_file(request):
    """Descarga el archivo de logs completo."""
    log_file_path = os.environ.get('LOG_FILE_PATH', r'c:\data\logs\dentfact.log')
    
    if os.path.exists(log_file_path):
        return FileResponse(
            open(log_file_path, 'rb'),
            as_attachment=True,
            filename='dentfact.log'
        )
    return HttpResponseNotFound('Archivo de log no encontrado')


@login_required(login_url='/auth/login/')
def clear_logs(request):
    """Limpia el archivo de logs."""
    log_file_path = os.environ.get('LOG_FILE_PATH', r'c:\data\logs\dentfact.log')
    
    try:
        if os.path.exists(log_file_path):
            with open(log_file_path, 'w', encoding='utf-8') as f:
                f.write('')
            logger.info("Archivo de logs limpiado correctamente")
            messages.success(request, 'Logs eliminados correctamente')
        else:
            messages.warning(request, 'Archivo de logs no existe')
        
        return redirect('home:view_logs')
    
    except Exception as e:
        logger.error(f"Error al limpiar logs: {e}", exc_info=True)
        messages.error(request, f'Error al limpiar logs: {str(e)}')
        return redirect('home:view_logs')




#########################################################

# ------------------------------------------
# Configuración - CONSOLIDATED AND FIXED
# ------------------------------------------

from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect

@login_required(login_url='/auth/login/')
def config_paths(request):
    """Display configuration editor page"""
    active_page = 'config'
    return render(request, 'config.html', {'active_page': active_page})


@login_required
@require_http_methods(['GET'])
def config_load(request):
    """
    Load configuration from INI file.
    Returns config in nested dictionary format that matches the template.
    Handles case-sensitive key matching from the config.ini file.
    """
    try:
        config_file = Path(r'c:\dentfact\config.ini')
        
        if not config_file.exists():
            logger.warning(f"Config file not found: {config_file}")
            return JsonResponse({
                'success': False,
                'error': f'Archivo de configuración no encontrado: {config_file}'
            }, status=404)
        
        config = ConfigParser()
        config.read(config_file, encoding='utf-8')
        
        config_dict = {}
        for section in config.sections():
            config_dict[section] = {}
            for key, value in config.items(section):
                # Preserve the exact key name as stored in the file
                config_dict[section][key] = value
        
        logger.info(f"Configuration loaded successfully from {config_file}")
        logger.debug(f"Config loaded: {config_dict}")
        
        return JsonResponse({
            'success': True,
            'config': config_dict
        })
    
    except Exception as e:
        logger.error(f"Error loading configuration: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'Error al cargar configuración: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(['POST'])
@csrf_protect
def config_save(request):
    """
    Save configuration to INI file.
    Expects nested dictionary: {section: {key: value, ...}, ...}
    Properly preserves case and creates backup before saving.
    """
    try:
        data = json.loads(request.body)
        logger.info(f"Config data received for saving")
        logger.debug(f"Config data: {data}")
        
        config_file = Path(r'c:\dentfact\config.ini')
        
        if config_file.exists():
            backup_path = config_file.with_suffix('.ini.bak')
            try:
                import shutil
                shutil.copy2(config_file, backup_path)
                logger.info(f"Backup created: {backup_path}")
            except Exception as e:
                logger.warning(f"Could not create backup: {e}")
        
        config = ConfigParser()
        if config_file.exists():
            config.read(config_file, encoding='utf-8')
        
        for section, values in data.items():
            if not config.has_section(section):
                config.add_section(section)
            
            config.remove_section(section)
            config.add_section(section)
            
            if isinstance(values, dict):
                for key, value in values.items():
                    str_value = str(value).strip() if value is not None else ''
                    config.set(section, key, str_value)
                    logger.debug(f"Set [{section}] {key} = {str_value}")
        
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_file, 'w', encoding='utf-8') as f:
            config.write(f)
        
        logger.info(f"Configuration saved successfully to {config_file}")
        
        return JsonResponse({
            'success': True,
            'message': 'Configuración guardada correctamente',
            'config_path': str(config_file)
        })
    
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config_save: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Formato JSON inválido'
        }, status=400)
    
    except Exception as e:
        logger.error(f"Error saving configuration: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'Error al guardar configuración: {str(e)}'
        }, status=500)


# ------------------------------------------
# Actualización de tablas y facturas
# ------------------------------------------
@login_required(login_url='/auth/login/')
def updCentro(request):
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return render(request, 'centro.html', {'timestamp': timestamp, 'active_page': 'tables'})
    except Exception as e:
        logger.error(f"Error en updCentro: {e}", exc_info=True)
        return render(request, 'centro.html', {'error': str(e), 'active_page': 'tables'})

@login_required(login_url='/auth/login/')
def updSociedad(request):
    try:
        df_importes = vf.get_importes(tablas, sqlite3_dbpath)
        if df_importes is None or df_importes.empty:
            return HttpResponse("Error: No se pudieron obtener los datos de importes", status=500)
        result = vu.updTables(df_importes)
        if not result:
            return HttpResponse("Error: Falló la actualización de sociedades", status=500)
        return render(request, 'empresa.html')
    except Exception as e:
        logger.error(f"Error en updSociedad: {e}", exc_info=True)
        return HttpResponse(f"Error inesperado: {str(e)}", status=500)

@login_required(login_url='/auth/login/')
def updEspecialidad(request):
    context = {}
    try:
        resultado = vu.updEspecialidad_csv()
        context = {
            'status': 'success',
            'message': 'Actualización completada con éxito',
            'updated': True,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    except Exception as e:
        logger.error(f"Error en updEspecialidad: {e}", exc_info=True)
        context = {'status': 'error', 'message': str(e), 'updated': False}
    return render(request, 'especialidad.html', context)

@login_required(login_url='/auth/login/')
def updImportes(request):
    try:
        df_importes = vf.get_importes(tablas, sqlite3_dbpath)
        if df_importes is None or df_importes.empty:
            return HttpResponse("Error: No se pudieron obtener los datos de importes", status=500)
        return render(request, 'importes.html')
    except Exception as e:
        logger.error(f"Error en updImportes: {e}", exc_info=True)
        return HttpResponse(f"Error inesperado: {str(e)}", status=500)

@login_required(login_url='/auth/login/')
def updFactura_R(request):
    try:
        result = vp.init_pdf()
        if not result:
            return HttpResponse("Error: Falló la carga de las facturas (pdf))", status=500)
        return render(request, 'factura_r.html')
    except Exception as e:
        logger.error(f"Error en updFactura_R: {e}", exc_info=True)
        return HttpResponse(f"Error inesperado: {str(e)}", status=500)

@login_required(login_url='/auth/login/')
def updFactura_C(request):
    try:
        success = vf.init_factura()
        if not success:
            return HttpResponse("Error: Falló la inicialización de facturas por centros", status=500)
        return render(request, 'factura_c.html')
    except Exception as e:
        logger.error(f"Error en updFactura_C: {e}", exc_info=True)
        return HttpResponse(f"Error inesperado: {str(e)}", status=500)

@login_required(login_url='/auth/login/')
def updFactura_D(request):
    try:
        success = vf.init_factura()
        
        if not success:
            return HttpResponse("Error: Falló la inicialización de facturas por dentista", status=500)
        return render(request, 'factura_d.html')
    except Exception as e:
        logger.error(f"Error en updFactura_D: {e}", exc_info=True)
        return HttpResponse(f"Error inesperado: {str(e)}", status=500)

# ------------------------------------------
# Listados
# ------------------------------------------
@login_required(login_url='/auth/login/')
def doctor_list(request):
    return render(request, 'doctor.html')

@login_required(login_url='/auth/login/')
def docpercent_list(request):
    return render(request, 'doctor.html')

@login_required(login_url='/auth/login/')
#def centro_list(request):
#    return render(request, 'centro.html')

@login_required(login_url='/auth/login/')
def centro_list(request):
    return render(request, 'centro.html', {'active_page': 'tables'})




@login_required(login_url='/auth/login/')
def empresa_list(request):
    return render(request, 'empresa.html')

@login_required(login_url='/auth/login/')
def especialidad_list(request):
    return render(request, 'especialidad.html')

@login_required(login_url='/auth/login/')
def importes_list(request):
    return render(request, 'importes.html')

@login_required(login_url='/auth/login/')
def factura_r_list(request):
    try:
        manager = getattr(Factura_R, 'objects', None)
        if manager is None:
            manager = getattr(Factura_R, '_default_manager', None)
            if manager is None:
                facturas = []
            else:
                facturas = manager.all()
        else:
            facturas = manager.all()
        serialized = Factura_RSerializer(facturas, many=True).data
        return render(request, 'factura_r.html', {'facturas': serialized})
    except Exception as e:
        logger.error(f"Error en factura_r_list: {e}", exc_info=True)
        return render(request, 'error.html', {'error_message': str(e)})

@login_required(login_url='/auth/login/')
def factura_c_list(request):
    try:
        manager = getattr(Factura_C, 'objects', None)
        if manager is None:
            manager = getattr(Factura_C, '_default_manager', None)
        if manager is None:
            facturas = []
        else:
            facturas = manager.all()
        return render(request, 'factura_c.html', {'facturas': facturas})
    except Exception as e:
        logger.error(f"Error en factura_c_list: {e}", exc_info=True)
        return render(request, 'error.html', {'error_message': str(e)})

@login_required(login_url='/auth/login/')
def factura_d_list(request):
    try:
        manager = getattr(Factura_D, 'objects', None)
        if manager is None:
            manager = getattr(Factura_D, '_default_manager', None)
        if manager is None:
            facturas = []
        else:
            facturas = manager.all()
        serialized = Factura_DSerializer(facturas, many=True).data
        return render(request, 'factura_d.html', {'facturas': serialized})
    except Exception as e:
        logger.error(f"Error en factura_d_list: {e}", exc_info=True)
        return render(request, 'error.html', {'error_message': str(e)})

@login_required(login_url='/auth/login/')
def factura_v_list(request):
    return render(request, 'factura_v.html')


@login_required(login_url='/auth/login/')

def factura_ou_prn(request, pk):
    factura_d = get_object_or_404(Factura_D, FACTURA=pk)
    factura_v = Factura_V.objects.filter(factura=factura_d).first()
    if not factura_v:
        logger.warning(f"No Veri*Factu data for FACTURA {pk}")
    context = {
        'factura': factura_d,
        'factura_v': factura_v,
        'generated_at': timezone.now()  
        }
    return render(request, 'factura_ou_fmt.html', context)
# ------------------------------------------
# Registro de usuarios
# ------------------------------------------
def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Registro exitoso. ¡Bienvenido!')
            return redirect('dashboard')
        messages.error(request, 'Error al registrar. Por favor, revisa los campos.')
    else:
        form = UserCreationForm()
    return render(request, 'login.html', {'form': form})

# ------------------------------------------
# ViewSets y API
# ------------------------------------------
def create_docpercent(request):
    data = request.data

    try:
        doctor_instance = Doctor.objects.get(SPCODE=data['SPCODE'])
    except Doctor.DoesNotExist:
        return Response({'error': 'Doctor no encontrado'}, status=status.HTTP_404_NOT_FOUND)

    if Docpercent.objects.filter(SPCODE=doctor_instance, ESPECIALIDAD=data['ESPECIALIDAD'], CENTRO=data['CENTRO']).exists():
        return Response({'error': 'Docpercent ya existe'}, status=status.HTTP_400_BAD_REQUEST)

    data['SPCODE'] = doctor_instance.id
    serializer = DocpercentSerializer(data=data)

    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# ViewSets

class DocpercentViewSet(viewsets.ModelViewSet):
    queryset = Docpercent.objects.all()
    serializer_class = DocpercentSerializer
    
    def get_queryset(self):
        queryset = Docpercent.objects.all()
        spcode = self.request.query_params.get('spcode', None)
        especialidad = self.request.query_params.get('especialidad', None)
        centro = self.request.query_params.get('centro', None)
        
        if spcode:
            queryset = queryset.filter(SPCODE__SPCODE=spcode)
        if especialidad:
            queryset = queryset.filter(ESPECIALIDAD=especialidad)
        if centro:
            queryset = queryset.filter(CENTRO=centro)
        
        return queryset
    
    def retrieve(self, request, spcode=None, especialidad=None, centro=None):
        """Obtiene un registro específico usando la clave compuesta"""
        try:
            # Obtener el doctor por SPCODE
            doctor = Doctor.objects.get(SPCODE=spcode)
            
            # Buscar el registro de docpercent
            docpercent = Docpercent.objects.get(
                SPCODE=doctor,
                ESPECIALIDAD=especialidad,
                CENTRO=centro
            )
            
            serializer = self.get_serializer(docpercent)
            return Response(serializer.data)
        except Doctor.DoesNotExist:
            return Response(
                {'error': f'Doctor con SPCODE {spcode} no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Docpercent.DoesNotExist:
            return Response(
                {'error': f'Registro no encontrado para SPCODE={spcode}, ESPECIALIDAD={especialidad}, CENTRO={centro}'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def update(self, request, spcode=None, especialidad=None, centro=None):
        """Actualiza un registro usando la clave compuesta"""
        try:
            # Obtener el doctor por SPCODE
            doctor = Doctor.objects.get(SPCODE=spcode)
            
            # Buscar el registro de docpercent
            docpercent = Docpercent.objects.get(
                SPCODE=doctor,
                ESPECIALIDAD=especialidad,
                CENTRO=centro
            )
            
            serializer = self.get_serializer(docpercent, data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            
            return Response(serializer.data)
        except Doctor.DoesNotExist:
            return Response(
                {'error': f'Doctor con SPCODE {spcode} no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Docpercent.DoesNotExist:
            return Response(
                {'error': f'Registro no encontrado para SPCODE={spcode}, ESPECIALIDAD={especialidad}, CENTRO={centro}'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def partial_update(self, request, spcode=None, especialidad=None, centro=None):
        """Actualiza parcialmente un registro usando la clave compuesta"""
        try:
            # Obtener el doctor por SPCODE
            doctor = Doctor.objects.get(SPCODE=spcode)
            
            # Buscar el registro de docpercent
            docpercent = Docpercent.objects.get(
                SPCODE=doctor,
                ESPECIALIDAD=especialidad,
                CENTRO=centro
            )
            
            serializer = self.get_serializer(docpercent, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            
            return Response(serializer.data)
        except Doctor.DoesNotExist:
            return Response(
                {'error': f'Doctor con SPCODE {spcode} no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Docpercent.DoesNotExist:
            return Response(
                {'error': f'Registro no encontrado para SPCODE={spcode}, ESPECIALIDAD={especialidad}, CENTRO={centro}'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def destroy(self, request, spcode=None, especialidad=None, centro=None):
        """Elimina un registro usando la clave compuesta"""
        try:
            # Obtener el doctor por SPCODE
            doctor = Doctor.objects.get(SPCODE=spcode)
            
            # Buscar el registro de docpercent
            docpercent = Docpercent.objects.get(
                SPCODE=doctor,
                ESPECIALIDAD=especialidad,
                CENTRO=centro
            )
            
            docpercent.delete()
            
            return Response(
                {'message': 'Registro eliminado correctamente'},
                status=status.HTTP_204_NO_CONTENT
            )
        except Doctor.DoesNotExist:
            return Response(
                {'error': f'Doctor con SPCODE {spcode} no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Docpercent.DoesNotExist:
            return Response(
                {'error': f'Registro no encontrado para SPCODE={spcode}, ESPECIALIDAD={especialidad}, CENTRO={centro}'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DoctorViewSet(viewsets.ModelViewSet):
    queryset = Doctor.objects.all()
    serializer_class = DoctorSerializer
    permission_classes = [IsAuthenticated]

    def validate_dni(self, dni):
        """
        Valida el formato del DNI español (8 dígitos + 1 letra)
        """
        import re
        if not dni:
            return False
        dni_pattern = r'^[0-9]{8}[A-Z]$'
        return bool(re.match(dni_pattern, dni.upper()))

    def create(self, request, *args, **kwargs):
        """
        Crea un nuevo registro de Doctor con validaciones
        """
        try:
            if 'DNI' in request.data and request.data['DNI']:
                if not self.validate_dni(request.data['DNI']):
                    return Response(
                        {'error': 'DNI inválido: debe tener 8 dígitos y una letra'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            required_fields = ['NOMBRE', 'I_APELLIDO']
            missing_fields = [field for field in required_fields if not request.data.get(field)]
            if missing_fields:
                return Response(
                    {'error': f'Campos requeridos faltantes: {", ".join(missing_fields)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            serializer = self.get_serializer(data=request.data)
            
            if serializer.is_valid():
                self.perform_create(serializer)
                logger.info(f"Doctor creado: {serializer.data.get('SPCODE')}")
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            else:
                logger.error(f"Errores de validación en create: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            logger.error(f"Error en create Doctor: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Error al crear doctor: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def update(self, request, *args, **kwargs):
        """
        Actualiza un registro de Doctor con validaciones mejoradas
        """
        try:
            partial = kwargs.pop('partial', False)
            instance = self.get_object()
            
            if 'DNI' in request.data and request.data['DNI']:
                if not self.validate_dni(request.data['DNI']):
                    return Response(
                        {'error': 'DNI inválido: debe tener 8 dígitos y una letra'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            
            if serializer.is_valid():
                self.perform_update(serializer)
                logger.info(f"Doctor actualizado: {instance.SPCODE}")
                return Response(serializer.data)
            else:
                logger.error(f"Errores de validación en update: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            logger.error(f"Error en update Doctor: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Error al actualizar doctor: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def partial_update(self, request, *args, **kwargs):
        """
        Actualiza parcialmente un registro de Doctor
        """
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """
        Elimina un registro de Doctor verificando dependencias
        """
        try:
            instance = self.get_object()
            spcode = instance.SPCODE
            
            docpercent_count = Docpercent.objects.filter(SPCODE=spcode).count()
            
            if docpercent_count > 0:
                logger.warning(f"Intento de eliminar Doctor {spcode} con {docpercent_count} porcentajes asociados")
            
            instance.delete()
            logger.info(f"Doctor eliminado: {spcode}")
            return Response(
                {'message': 'Doctor eliminado correctamente'},
                status=status.HTTP_204_NO_CONTENT
            )
            
        except Exception as e:
            logger.error(f"Error en destroy Doctor: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Error al eliminar doctor: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def retrieve(self, request, *args, **kwargs):
        """
        Recupera un registro específico de Doctor
        """
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error en retrieve Doctor: {str(e)}")
            return Response(
                {'error': 'Doctor no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
class CentroViewSet(viewsets.ModelViewSet):
    serializer_class = CentroSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        manager = getattr(Centro, 'objects', None)
        if manager is None:
            manager = getattr(Centro, '_default_manager', None)
            if manager is None:
                return []
        return manager.all()

class EmpresaViewSet(viewsets.ModelViewSet):
    serializer_class = EmpresaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        manager = getattr(Sociedad, 'objects', None)
        if manager is None:
            manager = getattr(Sociedad, '_default_manager', None)
            if manager is None:
                return []
        return manager.all()

class EspecialidadViewSet(viewsets.ModelViewSet):
    serializer_class = EspecialidadSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        manager = getattr(Especialidad, 'objects', None)
        if manager is None:
            manager = getattr(Especialidad, '_default_manager', None)
            if manager is None:
                return []
        return manager.all()

class ImportesViewSet(viewsets.ModelViewSet):
    serializer_class = ImportesSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        manager = getattr(Importes, 'objects', None)
        if manager is None:
            manager = getattr(Importes, '_default_manager', None)
            if manager is None:
                return []
        return manager.all()

class Factura_RViewSet(viewsets.ModelViewSet):
    serializer_class = Factura_RSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        manager = getattr(Factura_R, 'objects', None)
        if manager is None:
            manager = getattr(Factura_R, '_default_manager', None)
            if manager is None:
                return []
        return manager.all()

class Factura_CViewSet(viewsets.ModelViewSet):
    serializer_class = Factura_CSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        manager = getattr(Factura_C, 'objects', None)
        if manager is None:
            manager = getattr(Factura_C, '_default_manager', None)
            if manager is None:
                return []
        return manager.all()

class Factura_DViewSet(viewsets.ModelViewSet):
    serializer_class = Factura_DSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        manager = getattr(Factura_D, 'objects', None)
        if manager is None:
            manager = getattr(Factura_D, '_default_manager', None)
            if manager is None:
                return []
        return manager.all()

class Factura_VViewSet(viewsets.ModelViewSet):
    serializer_class = Factura_VSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        manager = getattr(Factura_V, 'objects', None)
        if manager is None:
            return []
        return manager.all()
###################################################################################################
#
#   Funciones para la plantilla de impresión de la factura
#
######################################################################################################

from django.http import JsonResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import configparser
import os
from pathlib import Path

@require_http_methods(["GET"])
def get_config(request):
    """
    Lee la configuración del archivo c:\\dentfact\\config.ini
    y devuelve la ruta de guardado de PDFs
    """
    try:
        config = configparser.ConfigParser()
        config_path = r'c:\dentfact\config.ini'
        
        if not os.path.exists(config_path):
            return JsonResponse({
                'error': 'Archivo de configuración no encontrado',
                'pdf_save_path': ''
            }, status=404)
        
        config.read(config_path, encoding='utf-8')
        
        pdf_save_path = config.get('paths', 'pdf_save_path', fallback='')
        
        return JsonResponse({
            'pdf_save_path': pdf_save_path,
            'smtp_host': config.get('smtp', 'host', fallback=''),
            'smtp_port': config.get('smtp', 'port', fallback='587'),
            'smtp_user': config.get('smtp', 'user', fallback=''),
            'smtp_from': config.get('smtp', 'from', fallback='')
        })
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'pdf_save_path': ''
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def send_factura(request, factura_id):
    """
    Envía la factura por correo electrónico con el PDF adjunto
    Lee la configuración SMTP de config.ini
    """
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    
    try:
        config = configparser.ConfigParser()
        config.read(r'c:\dentfact\config.ini', encoding='utf-8')
        
        smtp_host = config.get('smtp', 'host')
        smtp_port = config.getint('smtp', 'port')
        smtp_user = config.get('smtp', 'user')
        smtp_password = config.get('smtp', 'password')
        smtp_from = config.get('smtp', 'from')
        
        to_email = request.POST.get('to')
        doctor = request.POST.get('doctor')
        periodo = request.POST.get('periodo')
        pdf_file = request.FILES.get('pdf')
        
        if not all([to_email, doctor, periodo, pdf_file]):
            return JsonResponse({
                'error': 'Faltan datos requeridos'
            }, status=400)
        
        msg = MIMEMultipart()
        msg['From'] = smtp_from
        msg['To'] = to_email
        msg['Subject'] = f'Factura {factura_id} - {doctor} - Período {periodo}'
        
        body = f"""
        Estimado/a,
        
        Adjunto encontrará la factura {factura_id} correspondiente al período {periodo}.
        
        Doctor: {doctor}
        
        Esta factura cumple con la normativa VERI*FACTU de la AEAT.
        
        Saludos cordiales,
        DENTFACT
        """
        msg.attach(MIMEText(body, 'plain'))
        
        pdf_attachment = MIMEApplication(pdf_file.read(), _subtype='pdf')
        pdf_attachment.add_header('Content-Disposition', 'attachment', filename=pdf_file.name)
        msg.attach(pdf_attachment)
        
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        
        return JsonResponse({
            'success': True,
            'message': f'Factura enviada correctamente a {to_email}'
        })
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'success': False
        }, status=500)


@require_http_methods(["GET"])
def validate_qr(request, factura_id):
    """
    Valida específicamente el código QR de la factura
    según la normativa VERI*FACTU
    """
    try:
        from .models import Factura_V
        import qrcode
        from io import BytesIO
        import base64

        factura_v = Factura_V.objects.get(factura_id=factura_id)
        
        qr_data = f"https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR?nif={factura_v.nif}&numfactura={factura_id}&fecha={factura_v.fecha_emision}&importe={factura_v.total}"
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        is_valid = all([
            factura_v.hash and len(factura_v.hash) == 64,
            factura_v.sif_id and len(factura_v.sif_id) >= 8,
            factura_v.qr_base64 is not None
        ])
        
        return JsonResponse({
            'isValid': is_valid,
            'details': 'Código QR válido según normativa VERI*FACTU' if is_valid else 'Código QR inválido',
            'qr_data': {
                'url': qr_data,
                'hash': factura_v.hash,
                'sif_id': factura_v.sif_id,
                'fecha_emision': str(factura_v.fecha_emision)
            }
        })
    except Exception as e:
        return JsonResponse({
            'isValid': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='/auth/login/')
def load_log_json(request):
    """Devuelve los logs en formato JSON para refrescos dinámicos."""
    log_file_path = os.environ.get('LOG_FILE_PATH', r'c:\data\logs\dentfact.log')
    logs_list = []
    try:
        if not os.path.exists(log_file_path):
            return JsonResponse({
                'success': False,
                'error': 'Archivo de logs no existe.',
                'logs': [],
                'file_path': log_file_path,
                'file_size': 0
            }, status=404)
        
        file_size = os.path.getsize(log_file_path)
        with open(log_file_path, 'rb') as f:
            raw_data = f.read()
            enc = chardet.detect(raw_data)['encoding'] or 'utf-8'
        with open(log_file_path, 'r', encoding=enc) as f:
            for line in f:
                parts = line.strip().split(' ', 3)
                if len(parts) >= 4:
                    nivel, fecha, hora, resto = parts
                    resto_parts = resto.split(' ', 1)
                    module = resto_parts[0]
                    mensaje = resto_parts[1] if len(resto_parts) > 1 else ''
                    logs_list.append({
                        'fecha': fecha,
                        'hora': hora,
                        'nivel': nivel,
                        'module': module,
                        'mensaje': mensaje
                    })
        return JsonResponse({
            'success': True,
            'logs': logs_list,
            'file_path': log_file_path,
            'file_size': file_size,
            'lines': logs_list
        })
    except Exception as e:
        logger.error(f"Error en load_log_json: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'Error al cargar logs: {str(e)}',
            'logs': [],
            'file_path': log_file_path,
            'file_size': 0
        }, status=500)
        
@login_required(login_url='/auth/login/')
def clear_logs(request):
    path = os.environ.get('LOG_FILE_PATH', r'c:\data\logs\dentfact.log')
    try:
        if os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                f.write('')
            logger.info("Archivo de logs limpiado")
            messages.success(request, 'Logs eliminados correctamente')
        else:
            messages.error(request, 'Archivo de logs no existe')
        return redirect('home:view_logs')  # Redirige a la vista de logs
    except Exception as e:
        logger.error(f"Error al limpiar logs: {e}", exc_info=True)
        messages.error(request, str(e))
        return redirect('home:view_logs')
    

# Ruta del archivo de log
LOG_PATH = r"C:\data\log\dentfact.log"


def parse_log_line(line):
    """
    Parsea una línea del archivo de log y devuelve un diccionario con sus campos.
    Ejemplo de línea:
      2025-10-23 14:02:10,120 INFO [views_rag.py:88] RAGService inicializado
    """
    pattern = r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2}),?\d*\s+(\w+)\s+(.*)$"
    match = re.match(pattern, line)
    if match:
        fecha, hora, nivel, mensaje = match.groups()
        return {
            "fecha": fecha,
            "hora": hora,
            "nivel": nivel,
            "module": "",
            "mensaje": mensaje.strip(),
        }
    else:
        return {
            "fecha": "",
            "hora": "",
            "nivel": "INFO",
            "module": "",
            "mensaje": line.strip(),
        }


def download_log_file(request):
    """
    Descarga el archivo dentfact.log completo.
    """
    try:
        if os.path.exists(LOG_PATH):
            return FileResponse(
                open(LOG_PATH, "rb"), as_attachment=True, filename="dentfact.log"
            )
        return JsonResponse({"success": False, "error": "Archivo no encontrado"})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})
