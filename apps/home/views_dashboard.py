# views_dashboard.py

import json
import decimal
import sqlite3
import logging
from datetime import datetime

from django.shortcuts import render
from typing import Tuple, Dict, Any
from django.http import JsonResponse, HttpRequest
from django.db import connection
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.template import TemplateDoesNotExist
from django.http import HttpResponse

# Configuración para ejecución independiente
import django
import os

logger = logging.getLogger(__name__)

# Constantes globales
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", 
         "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
COLOR_PALETTE = ["#FF5733", "#33FF57", "#3357FF", "#FF33A8", "#A833FF", "#33FFF5", "#F5FF33"]

# ------------------- FUNCIONES AUXILIARES -------------------

def dictfetchall(cursor):
    r"""Convierte los resultados de un cursor en una lista de diccionarios."""
    try:
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    except AttributeError as e:
        logger.error(f"Error en descripción del cursor: {e}")
        return []
    except Exception as e:
        logger.error(f"Error inesperado al obtener datos del cursor: {e}")
        return []

def format_currency(value):
    r"""Formatea un valor numérico como moneda europea."""
    if value is None:
        return "0,00 €"
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

# ------------------- FUNCIONES DE CONSULTA -------------------

def get_F_Conteos(cursor):
    logger.info("Obteniendo conteos de entidades.")
    queries = {
        'sociedades_count': "SELECT COUNT(*) FROM dentfact_sociedad",
        'centros_count': "SELECT COUNT(*) FROM dentfact_centro",
        'doctores_count': "SELECT COUNT(*) FROM dentfact_doctor",
        'especialidades_count': "SELECT COUNT(*) FROM dentfact_especialidad"
    }
    conteos = {key: 0 for key in queries}
    try:
        for key, query in queries.items():
            cursor.execute(query)
            conteos[key] = cursor.fetchone()[0] or 0
            logger.info(f"{key}: {conteos[key]} registros")
    except Exception as e:
        logger.error(f"Error al obtener conteos: {e}")
    return conteos

def get_F_FacGasTot(cursor, current_year):
    logger.info("Obteniendo facturación y gastos totales.")
    year_str = str(current_year)
    query = """
        SELECT 
            SUM(CAST(REPLACE(REPLACE(REPLACE(COALESCE(TOTAL_FACTURA, '0'), ' €', ''), '.', ''), ',', '.') AS REAL)) AS total_facturacion,
            SUM(CAST(REPLACE(REPLACE(REPLACE(COALESCE(GASTOS, '0'), ' €', ''), '.', ''), ',', '.') AS REAL)) AS total_gastos
        FROM dentfact_factura_d 
        WHERE ANNO = :year
    """
    try:
        cursor.execute(query, {'year': year_str})
        result = cursor.fetchone()
        total_facturacion = result[0] if result and result[0] is not None else 0
        total_gastos = result[1] if result and result[1] is not None else 0
        logger.info(f"Total facturación: {total_facturacion}, Total gastos: {total_gastos}")
        return {
            'total_facturacion': format_currency(total_facturacion).strip(),
            'total_gastos': format_currency(total_gastos).strip()
        }
    except sqlite3.Error as db_err:
        logger.error(f"Error de base de datos: {db_err}")
        return {'total_facturacion': "0,00 €", 'total_gastos': "0,00 €"}
    except Exception as e:
        logger.error(f"Error inesperado: {e}")
        return {'total_facturacion': "0,00 €", 'total_gastos': "0,00 €"}

def get_F_FacGasMes(cursor, current_year):
    facturacion_mes = {mes: 0 for mes in MESES}
    gastos_mes = {mes: 0 for mes in MESES}
    try:
        year_str = str(current_year)
        query = """
            SELECT MES, 
                   SUM(CAST(REPLACE(REPLACE(REPLACE(COALESCE(TOTAL_FACTURA, '0'), ' €', ''), '.', ''), ',', '.') AS REAL)) AS suma_facturacion,
                   SUM(CAST(REPLACE(REPLACE(REPLACE(COALESCE(GASTOS, '0'), ' €', ''), '.', ''), ',', '.') AS REAL)) AS suma_gastos
            FROM dentfact_factura_d 
            WHERE ANNO = :year 
            GROUP BY MES
        """
        cursor.execute(query, {'year': year_str})
        results = dictfetchall(cursor)
        for row in results:
            try:
                mes_idx = int(row['MES']) - 1
                if 0 <= mes_idx < 12:
                    facturacion_mes[MESES[mes_idx]] = row['suma_facturacion'] or 0
                    gastos_mes[MESES[mes_idx]] = row['suma_gastos'] or 0
                    logger.info(f"{MESES[mes_idx]}: Facturación {facturacion_mes[MESES[mes_idx]]}, Gastos {gastos_mes[MESES[mes_idx]]}")
            except (ValueError, TypeError):
                logger.warning(f"Valor inválido para MES: {row.get('MES')}")
                continue
        mensuales = {}
        for mes in MESES:
            mensuales[f'{mes}_facturacion'] = format_currency(facturacion_mes[mes]).replace(" €", "")
            mensuales[f'{mes}_gastos'] = format_currency(gastos_mes[mes]).replace(" €", "")
        return mensuales
    except Exception as e:
        logger.error(f"Error al obtener facturación y gastos mensuales: {e}")
        return {f'{mes}_{key}': "0,00" for mes in MESES for key in ['facturacion', 'gastos']}

def get_F_Sociedades(cursor, current_year):
    try:
        year_str = str(current_year)
        query = """
            SELECT SOCIEDAD, MES, 
                   SUM(CAST(REPLACE(REPLACE(REPLACE(COALESCE(TOTAL_FACTURA, '0'), ' €', ''), '.', ''), ',', '.') AS REAL)) AS total_facturacion 
            FROM dentfact_factura_d 
            WHERE ANNO = :year
            GROUP BY SOCIEDAD, MES
        """
        cursor.execute(query, {'year': year_str})
        sociedades_data = dictfetchall(cursor)
        sociedades_dict = {sociedad: [0.0]*12 for sociedad in set(row['SOCIEDAD'] for row in sociedades_data)}
        for row in sociedades_data:
            try:
                mes_idx = int(row['MES']) - 1
                if 0 <= mes_idx < 12:
                    sociedades_dict[row['SOCIEDAD']][mes_idx] = float(row['total_facturacion'] or 0)
                    logger.info(f"Sociedad {row['SOCIEDAD']}: {sociedades_dict[row['SOCIEDAD']][mes_idx]} en mes {row['MES']}")
            except (ValueError, TypeError):
                logger.warning(f"Valor inválido para MES: {row.get('MES')}")
                continue
        sociedades_data = [{
            'label': sociedad,
            'borderColor': COLOR_PALETTE[i % len(COLOR_PALETTE)],
            'backgroundColor': COLOR_PALETTE[i % len(COLOR_PALETTE)] + "20",
            'data': datos,
            'fill': False
        } for i, (sociedad, datos) in enumerate(sociedades_dict.items())]
        return {'sociedades_data': sociedades_data}
    except Exception as e:
        logger.error(f"Error al obtener facturación por sociedades: {e}")
        return {'sociedades_data': []}

def get_F_year(cursor):
    try:
        query_years = """
            SELECT DISTINCT SUBSTR(L_HASTA, 7, 4) AS year
            FROM dentfact_factura_c
            WHERE L_HASTA IS NOT NULL
            ORDER BY year
        """
        cursor.execute(query_years)
        years = [row[0] for row in cursor.fetchall() if row[0]]
        if not years:
            years = [str(datetime.now().year)]
        logger.info(f"Años encontrados: {years}")
        return years
    except Exception as e:
        logger.error(f"Error obteniendo años: {e}")
        return [str(datetime.now().year)]

def get_F_Centros(cursor, current_year):
    try:
        year_str = str(current_year)
        query = """
            SELECT CENTRO, 
                   TRIM(SUBSTR(L_HASTA, 4, 2)) AS MES, 
                   SUM(CAST(COALESCE(Neto, 0) AS REAL)) AS total_facturacion
            FROM dentfact_factura_c
            WHERE SUBSTR(L_HASTA, 7, 4) = :year
            GROUP BY CENTRO, TRIM(SUBSTR(L_HASTA, 4, 2))
            ORDER BY CENTRO, MES
        """
        cursor.execute(query, {'year': year_str})
        centros_data = dictfetchall(cursor)
        centros_dict = {}
        for row in centros_data:
            centro = row['CENTRO']
            try:
                mes_idx = int(row['MES']) - 1
            except (ValueError, TypeError):
                logger.warning(f"Valor inválido para MES: {row.get('MES')}")
                continue
            if centro not in centros_dict:
                centros_dict[centro] = [0]*12
            if 0 <= mes_idx < 12:
                centros_dict[centro][mes_idx] = float(row.get('total_facturacion', 0) or 0)
                logger.info(f"Centro {centro}: {centros_dict[centro][mes_idx]} en mes {row['MES']}")
        categories = [mes.capitalize() for mes in MESES]
        series = [{'name': centro, 'data': centros_dict[centro]} for centro in sorted(centros_dict.keys())]
        return {'categories': categories, 'series': series}
    except Exception as e:
        logger.error(f"Error en get_F_Centros: {str(e)}")
        return {'categories': [], 'series': []}

def get_F_Dentistas(cursor, current_year):
    try:
        year_str = str(current_year)
        query = """
            SELECT SPCODE, MES,
                   SUM(CAST(REPLACE(REPLACE(REPLACE(COALESCE(TOTAL_FACTURA, '0'), ' €', ''), '.', ''), ',', '.') AS REAL)) AS total_facturacion
            FROM dentfact_factura_d
            WHERE ANNO = :year
            GROUP BY SPCODE, MES
            ORDER BY SPCODE, MES
        """
        cursor.execute(query, {'year': year_str})
        dentistas_data = dictfetchall(cursor)
        dentistas_dict = {}
        for row in dentistas_data:
            dentista = row['SPCODE']
            try:
                mes_idx = int(row['MES']) - 1
            except (ValueError, TypeError):
                logger.warning(f"Valor inválido para MES: {row.get('MES')}")
                continue
            if dentista not in dentistas_dict:
                dentistas_dict[dentista] = [0]*12
            if 0 <= mes_idx < 12:
                dentistas_dict[dentista][mes_idx] = row['total_facturacion'] or 0
                logger.info(f"Dentista {dentista}: {dentistas_dict[dentista][mes_idx]} en mes {row['MES']}")
        series = [{
            'name': MESES[i].capitalize(),
            'data': [dentistas_dict[d][i] for d in sorted(dentistas_dict.keys())]
        } for i in range(12)]
        return {'categories': sorted(dentistas_dict.keys()), 'series': series}
    except Exception as e:
        logger.error(f"Error al obtener facturación por dentistas: {e}")
        return {'categories': [], 'series': []}

def get_F_Especialidades(cursor, current_year):
    try:
        year_str = str(current_year)
        query = """
            SELECT ESPECIALIDAD, 
                   SUM(CAST(REPLACE(REPLACE(REPLACE(COALESCE(BRUTO, '0'), ' €', ''), '.', ''), ',', '.') AS REAL)) AS total_facturacion 
            FROM dentfact_factura_c 
            WHERE SUBSTR(L_HASTA, 7, 4) = :year 
            GROUP BY ESPECIALIDAD
        """
        cursor.execute(query, {'year': year_str})
        especialidades_data = dictfetchall(cursor)
        logger.info(f"Especialidades: {len(especialidades_data)} registros")
        return [{
            'name': 'Facturación por especialidad',
            'colorByPoint': True,
            'data': [{'name': row['ESPECIALIDAD'], 'y': row['total_facturacion']} for row in especialidades_data]
        }]
    except Exception as e:
        logger.error(f"Error al obtener facturación por especialidades: {e}")
        return []

# ------------------- FUNCIONES AUXILIARES PARA VALIDACIÓN -------------------

def check_database():
    required_tables = [
        'dentfact_sociedad', 'dentfact_centro', 'dentfact_doctor',
        'dentfact_especialidad', 'dentfact_factura_d', 'dentfact_factura_c'
    ]
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        missing = [table for table in required_tables if table not in tables]
        if missing:
            logger.error(f"Tablas faltantes: {missing}")
            return False
        return True

# ------------------- GENERACIÓN DEL CONTEXTO -------------------

def generate_dashboard_context(selected_year: int) -> Dict[str, Any]:
    """
    Genera el contexto con los resultados de las consultas SQL para el año seleccionado.
    """
    logger.info(f"Generando contexto para el año {selected_year}")
    context = {}
    try:
        with connection.cursor() as cursor:
            years = get_F_year(cursor)
            logger.debug(f"Años obtenidos: {years}")

            conteos = get_F_Conteos(cursor)
            logger.debug(f"Conteos obtenidos: {conteos}")

            fac_gas_tot = get_F_FacGasTot(cursor, selected_year)
            logger.debug(f"Facturación/Gastos totales: {fac_gas_tot}")

            fac_gas_mes = get_F_FacGasMes(cursor, selected_year)
            logger.debug(f"Facturación/Gastos mensuales: {fac_gas_mes}")

            centros = get_F_Centros(cursor, selected_year)
            logger.debug(f"Datos de centros: {centros}")

            sociedades = get_F_Sociedades(cursor, selected_year)
            logger.debug(f"Datos de sociedades: {sociedades}")

            dentistas = get_F_Dentistas(cursor, selected_year)
            logger.debug(f"Datos de dentistas: {dentistas}")

            especialidades = get_F_Especialidades(cursor, selected_year)
            logger.debug(f"Datos de especialidades: {especialidades}")

            context.update(conteos)
            context.update(fac_gas_tot)
            context.update(fac_gas_mes)
            context['facturacion_centro_data'] = centros
            context['sociedades_data'] = sociedades['sociedades_data']
            context['facturacion_dentistas_data'] = dentistas
            context['facturacion_especialidad_data'] = especialidades
            context['facturacion_mensual'] = [fac_gas_mes.get(f'{mes}_facturacion', '0,00') for mes in MESES]
            context['gastos_mensual'] = [fac_gas_mes.get(f'{mes}_gastos', '0,00') for mes in MESES]
            context['years'] = years
            context['current_year'] = selected_year

            #logger.debug(f"Contexto generado: {context}")

    except Exception as e:
        logger.error(f"Error al generar contexto: {e}")
        context['error_message'] = str(e)

    return context

# ------------------- VISTA PRINCIPAL -------------------

@login_required(login_url='/auth/login/')
def dashboard(request):
    """
    Genera el cuadro de mando. Soporta:
    - Renderizado HTML para vistas normales
    - JSON para peticiones AJAX (actualización de gráficos)
    """
    logger.info("Inicio del proceso de generación del cuadro de mando.")
    context = {}
    current_year = timezone.now().year
    selected_year = request.GET.get('year', str(current_year))

    try:
        selected_year = int(selected_year)
    except ValueError:
        logger.warning(f"Valor inválido para 'year': {selected_year}, usando {current_year}")
        selected_year = current_year

    try:
        with connection.cursor() as cursor:
            # Obtener datos desde la base de datos
            years = get_F_year(cursor)
            conteos = get_F_Conteos(cursor)
            fac_gas_tot = get_F_FacGasTot(cursor, selected_year)
            fac_gas_mes = get_F_FacGasMes(cursor, selected_year)
            centros = get_F_Centros(cursor, selected_year)
            sociedades = get_F_Sociedades(cursor, selected_year)
            dentistas = get_F_Dentistas(cursor, selected_year)
            especialidades = get_F_Especialidades(cursor, selected_year)

            # Preparar contexto
            context.update(conteos)
            context.update(fac_gas_tot)
            context.update(fac_gas_mes)
            context['facturacion_centro_data'] = centros
            context['sociedades_data'] = sociedades['sociedades_data']
            context['facturacion_dentistas_data'] = dentistas
            context['facturacion_especialidad_data'] = especialidades
            context['facturacion_mensual'] = [fac_gas_mes.get(f'{mes}_facturacion', '0,00') for mes in MESES]
            context['gastos_mensual'] = [fac_gas_mes.get(f'{mes}_gastos', '0,00') for mes in MESES]
            context['years'] = years
            context['current_year'] = selected_year

            # 💡 Soporte AJAX: devolver JSON para la actualización de gráficos
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                response_data = {
                    'status': 'success',
                    'conteos': conteos,
                    'total_facturacion': fac_gas_tot['total_facturacion'],
                    'total_gastos': fac_gas_tot['total_gastos'],
                    'facturacion_mensual': context['facturacion_mensual'],
                    'gastos_mensual': context['gastos_mensual'],
                    'sociedades_data': sociedades['sociedades_data'],
                    'facturacion_centro_data': centros,
                    'facturacion_dentistas_data': dentistas,
                    'facturacion_especialidad_data': especialidades
                }
                return JsonResponse(response_data, encoder=DecimalEncoder)

            # Renderizar HTML normalmente
            return render(request, 'index.html', context)

    except Exception as e:
        logger.exception(f"Error en dashboard: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
        context['error_message'] = str(e)
        return render(request, 'error.html', context, status=500)
    
def init_dashboard(request):
    """
    Función que actúa como wrapper para invocar generate_dashboard_context desde otras vistas.
    Devuelve un tuple (context, success).
    """
    logger.info("Inicializando dashboard")
    selected_year = request.GET.get('year', str(timezone.now().year))
    try:
        selected_year = int(selected_year)
    except ValueError:
        selected_year = timezone.now().year

    try:
        context = generate_dashboard_context(selected_year)
        return context, True
    except Exception as e:
        logger.error(f"Error al inicializar dashboard: {e}")
        return {}, False

# ------------------- EJECUCIÓN INDEPENDIENTE -------------------

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')  # Ajustado según settings.py
    try:
        django.setup()
    except Exception as e:
        logger.error(f"Error al configurar el entorno Django: {e}", exc_info=True)
        print(f"Error al configurar el entorno Django: {str(e)}")
        exit(1)

    logger.info("Ejecutando views_dashboard.py de forma independiente")
    try:
        if not check_database():
            print("Error: Faltan tablas en la base de datos")
            exit(1)

        selected_year = timezone.now().year
        context = generate_dashboard_context(selected_year)

        # Verificar si los datos son solo valores por defecto
        scalar_values = [
            v for k, v in context.items()
            if isinstance(v, (int, str)) and k not in ('years', 'current_year')
        ]
        if all(v == 0 or v == "0,00 €" or v == "0,00" for v in scalar_values):
            logger.warning("Advertencia: Todos los datos escalares son valores por defecto. Verificar datos en la base de datos.")
            print("Advertencia: Todos los datos escalares son valores por defecto.")

        print("Contexto generado:")
        print(json.dumps(context, indent=2, cls=DecimalEncoder))
        output_path = r"C:\data\dashboard_context.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(context, f, indent=2, cls=DecimalEncoder)
        print(f"Contexto guardado en {output_path}")
    except Exception as e:
        logger.error(f"Error al ejecutar views_dashboard.py: {e}", exc_info=True)
        print(f"Error: {str(e)}")
        exit(1)