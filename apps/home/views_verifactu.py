import sqlite3
import pandas as pd
from pathlib import Path
from lxml import etree
import qrcode
import base64
import hashlib
from datetime import datetime
import io
import logging
import json
from django.http import JsonResponse
from django.db import transaction
import os
from apps.home import views_utils as vu
from configparser import ConfigParser

# Obtener el logger
logger = logging.getLogger(__name__)

# Configuración de paths
DB_PATH = Path(r"c:\data\dentfact.sqlite3")
XSD_PATH = Path(r"c:\data\aeat\VeriFactu_Registro.xsd")
EXPORT_PATH = Path(r"c:\data\verifactu_export")
EXPORT_PATH.mkdir(exist_ok=True)

VERIFACTU_URL = "https://sede.agenciatributaria.gob.es/verifactu/verificar"
NAMESPACE = "https://www2.agenciatributaria.gob.es/verifactu"
NSMAP = {"vf": NAMESPACE}

# --------------------------------------------------------------------
# CARGA DE CONFIGURACIÓN
# --------------------------------------------------------------------
CONFIG_PATH = Path(__file__).parent.parent.parent / 'config.ini'

def _load_config(path: Path) -> ConfigParser:
    cp = ConfigParser()
    if not path.exists():
        logger.critical("No se encontró el archivo de configuración: %s", path)
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {path}")
    cp.read(path, encoding='utf-8')
    return cp

def _validate_path(path_str: str, name: str) -> Path:
    clean_str = str(path_str).strip().strip('"').strip("'")
    p = Path(os.path.normpath(clean_str))
    if not p.exists():
        logger.error("La ruta %s no existe: %s", name, repr(p))
        raise FileNotFoundError(f"La ruta {name} no existe: {p}")
    return p

try:
    config = _load_config(CONFIG_PATH)
    tablas_dir = _validate_path(config.get('inputs', 'tablas'), 'tablas')
    logs_dir = _validate_path(config.get('outputs', 'logs'), 'logs')
    sqlite3_dbpath = config.get('outputs', 'sqlite3_dbpath', fallback='C:\\data\\dentfact.sqlite3')
    
    def _get_float(section: str, option: str, fallback: float) -> float:
        try:
            return config.getfloat(section, option, fallback=fallback)
        except Exception:
            logger.warning(f"No se pudo leer {option} en sección {section}. Usando fallback: {fallback}")
            return float(fallback)

    vGP = _get_float('default', 'GABINETE_PERCENTAGE', 0.115)
    vIVA = _get_float('default', 'IVA_PERCENTAGE', 0.21)
    vIRPF = _get_float('default', 'IRPF_PERCENTAGE', 0.15)
    vDD = config.getint('default', 'DD_FEMISION', fallback=21)
    vGASTOS = _get_float('default', 'GASTOS', 50)
    vPath = Path(r"c:\\data\\exports")
    vPath.mkdir(exist_ok=True)
except Exception as e:
    logger.critical("Error crítico al leer el archivo de configuración: %s", e, exc_info=True)
    raise

# Cargar esquema XSD
try:
    schema = etree.XMLSchema(etree.parse(str(XSD_PATH)))
except Exception as e:
    logger.error(f"Error cargando el esquema XSD: {e}")
    schema = None

# 1. Cargar datos desde la base de datos
def load_data():
    conn = sqlite3.connect(DB_PATH)
    df_factura_d = pd.read_sql_query("SELECT * FROM dentfact_factura_d", conn)
    conn.close()
    return df_factura_d

# 2. Reducir columnas
def reduce_columns(df):
    required_columns = [
        'FACTURA', 'EMISION', 'DOCTOR', 'DNI', 'CIF', 'SOCIEDAD',

        'GASTOS', 'IRPF', 'CUOTA_IRPF', 'BASE_FACTURA', 'BRUTO_TOTAL',
        'CALCULO', 'PORCENTAJE', 'TOTAL_FACTURA'
    ]
    # Filtrar solo las columnas que existen en el DataFrame
    existing_columns = [col for col in required_columns if col in df.columns]
    return df[existing_columns]

# 3. Parsear valores según normativa Veri*Factu (PRESERVANDO caso original de FACTURA)
def parse_values(df):
    df_parsed = df.copy()
    
    # --- FACTURA ---
    df_parsed['FACTURA'] = df_parsed['FACTURA'].astype(str).str.strip()

    # --- EMISION: Parsea '21/06/2025' a '2025-06-21' ---
    df_parsed['EMISION'] = pd.to_datetime(df_parsed['EMISION'], dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d')
    invalid_dates = df_parsed[df_parsed['EMISION'].isna()]
    if not invalid_dates.empty:
        logger.warning(f"Fechas inválidas en facturas: {invalid_dates['FACTURA'].tolist()} → usando hoy")
        df_parsed['EMISION'] = df_parsed['EMISION'].fillna(datetime.now().strftime('%Y-%m-%d'))

    # --- MONTOS: "894,28 €" → 894.28 (maneja . miles, , decimal) ---
    monetary_cols = ['GASTOS', 'CUOTA_IRPF', 'BASE_FACTURA', 'BRUTO_TOTAL', 'TOTAL_FACTURA']
    for col in monetary_cols:
        if col in df_parsed.columns:
            cleaned = (
                df_parsed[col]
                .astype(str)
                .str.strip()
                .str.replace(r'\.', '', regex=True)  # Quitar puntos de miles
                .str.replace(',', '.', regex=False)  # Coma a punto decimal
                .str.replace(r'[^0-9\.-]', '', regex=True)  # Quitar €, %
            )
            df_parsed[col] = pd.to_numeric(cleaned, errors='coerce').fillna(0.0).round(2)
            df_parsed[col] = df_parsed[col].clip(lower=0.0)

    # --- IRPF: "15.00%" → 15.0 ---
    if 'IRPF' in df_parsed.columns:
        irpf_pct = (
            df_parsed['IRPF']
            .astype(str)
            .str.strip()
            .str.extract(r'([0-9\.,]+)%')
            .iloc[:, 0]
            .str.replace(',', '.', regex=False)
            .astype(float, errors='ignore')
            .fillna(0.0)
            .clip(upper=100.0)
        )
        df_parsed['IRPF'] = irpf_pct
        logger.debug(f"IRPF parseado: {irpf_pct.head().to_list()}")

    return df_parsed
# 4. Funciones de generación
def _gen_SIF_ID(row):
    """Generar SIF_ID según normativa Veri*Factu"""
    emision = row['EMISION'].replace('-', '')
    # Asegurar que FACTURA esté en mayúsculas solo para el cálculo
    factura = str(row['FACTURA']).upper()
    total_factura = row.get('TOTAL_FACTURA', 0)
    # Formato: SIF- + hexadecimal (mínimo 17, máximo 32 caracteres hex)
    base_string = f"{factura}{emision}{total_factura:.2f}"
    hash_obj = hashlib.sha256(base_string.encode())
    hex_digest = hash_obj.hexdigest()[:30]  # Tomamos 30 caracteres hex para cumplir con el patrón
    return f"SIF-{hex_digest.upper()}"

def _gen_QR_CODE(row):
    """Generar código QR con datos de la factura"""
    qr_data = f"{VERIFACTU_URL}?id={_gen_SIF_ID(row)}"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    return img

def _gen_QR_BASE64(row):
    """Generar representación base64 del QR"""
    img = _gen_QR_CODE(row)
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode()

def _gen_HASH(row):
    """Generar hash de los datos de la factura"""
    # Asegurar que FACTURA esté en mayúsculas solo para el hash
    factura = str(row['FACTURA']).upper()
    total_factura = row.get('TOTAL_FACTURA', 0)
    base_imponible = row.get('BASE_FACTURA', 0)
    data_string = f"{factura}{row['EMISION']}{total_factura:.2f}{base_imponible:.2f}"
    return hashlib.sha256(data_string.encode()).hexdigest()

def _gen_PREVIOUS_HASH(df, current_index):
    """Generar hash del registro anterior"""
    if current_index == 0:
        return '0' * 64  # Hash inicial para el primer registro
    previous_hash = _gen_HASH(df.iloc[current_index - 1])
    return previous_hash

import re
def _safe_str(value, default=""):
    """Convierte valor a str seguro, con fallback"""
    return str(value).strip() if value is not None else default

def _gen_XML(row):
    try:
        factura = _safe_str(row.get('FACTURA', 'Unknown'))
        logger.debug(f"Generando XML para {factura}")

        root = etree.Element("{" + NAMESPACE + "}RegistroFacturacion", nsmap=NSMAP)

        # 1. NIF (primero)
        nif_raw = _safe_str(row.get('DNI', ''))
        nif_clean = re.sub(r'[^0-9A-Z]', '', nif_raw.upper())
        if not re.match(r'^[0-9A-Z]{8,9}[A-Z]?$', nif_clean):
            nif_clean = re.search(r'\d{8,9}[A-Z]?', nif_clean).group(0) if re.search(r'\d{8,9}[A-Z]?', nif_clean) else "00000000A"
        etree.SubElement(root, "{" + NAMESPACE + "}NIF").text = nif_clean[:15]

        # 2. NumFactura
        etree.SubElement(root, "{" + NAMESPACE + "}NumFactura").text = factura.upper()

        # 3. FechaExpedicion
        fecha = _safe_str(row.get('EMISION', datetime.now().strftime('%Y-%m-%d')))
        etree.SubElement(root, "{" + NAMESPACE + "}FechaExpedicion").text = fecha

        # 4. DescripcionOperacion
        etree.SubElement(root, "{" + NAMESPACE + "}DescripcionOperacion").text = f"Factura {factura} - Servicios odontológicos (exento IVA)"

        # 5. BaseImponible
        base = float(row.get('BASE_FACTURA', 0) or 0)
        if base <= 0:
            raise ValueError(f"BaseImponible <= 0 en {factura}")
        etree.SubElement(root, "{" + NAMESPACE + "}BaseImponible").text = f"{base:.2f}"

        # 6. CuotaIVA (exento)
        etree.SubElement(root, "{" + NAMESPACE + "}CuotaIVA").text = "0.00"

        # 7. IRPF
        irpf_pct = float(row.get('IRPF', 0) or 0)
        irpf_pct = min(irpf_pct, 100.0)
        etree.SubElement(root, "{" + NAMESPACE + "}IRPF").text = f"{irpf_pct:.2f}"

        # 8. CuotaIRPF
        cuota_irpf = float(row.get('CUOTA_IRPF', 0) or 0)
        cuota_calc = round(base * irpf_pct / 100, 2)
        if cuota_irpf == 0 and cuota_calc > 0:
            cuota_irpf = cuota_calc
            logger.warning(f"CuotaIRPF fallback: {cuota_irpf} para {factura}")
        etree.SubElement(root, "{" + NAMESPACE + "}CuotaIRPF").text = f"{cuota_irpf:.2f}"

        # 9. ImporteTotal = Base - CuotaIRPF
        total_calc = round(base - cuota_irpf, 2)
        total_csv = float(row.get('TOTAL_FACTURA', 0) or 0)
        if abs(total_calc - total_csv) > 0.01:
            logger.warning(f"Inconsistencia ImporteTotal: CSV={total_csv}, calc={total_calc} → usando calc si positivo")
        total = total_calc if total_calc > 0 else max(total_csv, 0)
        if total <= 0:
            raise ValueError(f"ImporteTotal <= 0 en {factura}")
        etree.SubElement(root, "{" + NAMESPACE + "}ImporteTotal").text = f"{total:.2f}"

        # 10. SIF_ID
        sif_id = _safe_str(row.get('SIF_ID', ''))
        if not sif_id.startswith('SIF-'):
            raise ValueError(f"SIF_ID inválido: {sif_id}")
        etree.SubElement(root, "{" + NAMESPACE + "}SIF_ID").text = sif_id

        # 11. Hash
        hash_val = _safe_str(row.get('HASH', ''))
        if not re.match(r'^[0-9a-fA-F]{64}$', hash_val):
            raise ValueError(f"Hash inválido: {hash_val}")
        etree.SubElement(root, "{" + NAMESPACE + "}Hash").text = hash_val

        # 12. HashAnterior
        prev_hash = _safe_str(row.get('PREVIOUS_HASH', '0' * 64))
        if not re.match(r'^[0-9a-fA-F]{64}$', prev_hash):
            prev_hash = '0' * 64
        etree.SubElement(root, "{" + NAMESPACE + "}HashAnterior").text = prev_hash

        # VALIDACIÓN XSD
        if schema:
            schema.assertValid(root)
            logger.info(f"XML válido para {factura}")

        return etree.tostring(root, encoding='unicode', pretty_print=True)

    except Exception as e:
        logger.error(f"Error XML para {factura}: {e}", exc_info=True)
        raise

    
# Pipeline principal CON VALIDACIONES
def validate_data_consistency():
    """
    Función auxiliar para validar la consistencia de datos entre
    dentfact_factura_d y dentfact_factura_v
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        
        # Contar registros en ambas tablas
        count_d = pd.read_sql_query("SELECT COUNT(*) as count FROM dentfact_factura_d", conn)
        count_v = pd.read_sql_query("SELECT COUNT(*) as count FROM dentfact_factura_v", conn)
        
        count_d_value = count_d['count'].iloc[0]
        count_v_value = count_v['count'].iloc[0]
        
        conn.close()
        
        is_consistent = count_d_value == count_v_value
        
        logger.info(f"VALIDACIÓN DE CONSISTENCIA:")
        logger.info(f"  - dentfact_factura_d: {count_d_value} registros")
        logger.info(f"  - dentfact_factura_v: {count_v_value} registros")
        logger.info(f"  - CONSISTENTE: {is_consistent}")
        
        return is_consistent, count_d_value, count_v_value
        
    except Exception as e:
        logger.error(f"Error en validación de consistencia: {e}")
        return False, 0, 0
#########################################################################################
# Función para exportar a XML (mantenida del código original)
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import connection
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# --- RUTA DE SALIDA ---
AEAT_EXPORT_PATH = Path(r"c:\data\aeat")
AEAT_EXPORT_PATH.mkdir(parents=True, exist_ok=True)

@csrf_exempt
def export2xml(request):
    """
    Exporta XMLs de facturas seleccionadas a un único archivo AEAT_ddmmaa_hhmm.XML
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Método no permitido. Usa POST."}, status=405)

    try:
        import json
        payload = json.loads(request.body)
        factura_ids = payload.get("facturas", [])
        
        if not factura_ids:
            return JsonResponse({"success": False, "error": "No se seleccionaron facturas."}, status=400)
        
        if not isinstance(factura_ids, list):
            return JsonResponse({"success": False, "error": "facturas debe ser una lista."}, status=400)

        logger.info(f"Exportando {len(factura_ids)} facturas a AEAT: {factura_ids[:5]}...")

        # --- 1. Consultar XMLs desde dentfact_factura_v ---
        with connection.cursor() as cursor:
            placeholders = ','.join(['%s'] * len(factura_ids))
            query = f"""
                SELECT FACTURA, XML 
                FROM dentfact_factura_v 
                WHERE FACTURA IN ({placeholders})
                  AND XML IS NOT NULL 
                  AND XML != ''
                ORDER BY EMISION, FACTURA
            """
            cursor.execute(query, factura_ids)
            rows = cursor.fetchall()

        if not rows:
            return JsonResponse({
                "success": False,
                "error": "Ninguna factura seleccionada tiene XML generado.",
                "incluidas": [],
                "errores": [f"{fid}: XML no encontrado" for fid in factura_ids]
            }, status=400)

        # --- 2. Separar válidas e inválidas ---
        validas = []
        errores = []

        factura_set = set(factura_ids)
        found_set = {row[0] for row in rows}

        for fid in factura_ids:
            if fid not in found_set:
                errores.append(f"{fid}: XML no generado")

        for factura, xml_content in rows:
            if xml_content and xml_content.strip():
                validas.append((factura, xml_content.strip()))
            else:
                errores.append(f"{factura}: XML vacío")

        if not validas:
            return JsonResponse({
                "success": False,
                "error": "No hay XMLs válidos para exportar.",
                "incluidas": [],
                "errores": errores
            }, status=400)

        # --- 3. Generar nombre de archivo: AEAT_ddmmaa_hhmm.XML ---
        now = datetime.now()
        filename = f"AEAT_{now.strftime('%d%m%y_%H%M')}.XML"
        filepath = AEAT_EXPORT_PATH / filename

        # --- 4. Concatenar XMLs con salto de línea ---
        full_content = "\n\n".join(xml_content for _, xml_content in validas)

        # --- 5. Guardar archivo ---
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(full_content)
            logger.info(f"Archivo AEAT exportado: {filepath} ({len(validas)} facturas)")
        except Exception as e:
            logger.error(f"Error al escribir archivo AEAT: {e}")
            return JsonResponse({"success": False, "error": f"No se pudo guardar el archivo: {e}"}, status=500)

        # --- 6. Respuesta al frontend ---
        return JsonResponse({
            "success": True,
            "archivo": str(filepath),
            "nombre": filename,
            "ruta": str(AEAT_EXPORT_PATH),
            "incluidas": [factura for factura, _ in validas],
            "total_incluidas": len(validas),
            "errores": errores,
            "mensaje": f"Exportadas {len(validas)} facturas a {filename}"
        })

    except Exception as e:
        logger.error(f"Error crítico en export2xml: {e}", exc_info=True)
        return JsonResponse({"success": False, "error": "Error interno del servidor."}, status=500)

def init_verifactu():
    """
    Función principal para inicializar el proceso Veri*Factu
    con validaciones de consistencia en el número de registros
    y preservación del caso original en FACTURA
    """
    try:
        logger.info("Iniciando proceso Veri*Factu con validaciones...")
        
        # Limpiar datos existentes en la tabla destino
        #clear_existing_data()
        
        # Cargar y preparar datos
        df_factura_d = vu.table2df(sqlite3_dbpath, 'dentfact_factura_d')
        original_count = len(df_factura_d)
        logger.info(f"Cargadas {original_count} facturas desde la base de datos")
        
        if original_count == 0:
            logger.warning("No hay facturas para procesar")
            return True
            
        # Validación 1: Después de reducir columnas
        df_factura_d = reduce_columns(df_factura_d)
        if len(df_factura_d) != original_count:
            logger.error(f"ERROR: Pérdida de registros después de reduce_columns. Original: {original_count}, Actual: {len(df_factura_d)}")
            return False
        
        # Validación 2: Después de parsear valores
        df_factura_d = parse_values(df_factura_d)
        if len(df_factura_d) != original_count:
            logger.error(f"ERROR: Pérdida de registros después de parse_values. Original: {original_count}, Actual: {len(df_factura_d)}")
            return False
        
        # Preparar DataFrame para resultados - FACTURA debe ser idéntica
        df_factura_v = pd.DataFrame()
        df_factura_v['FACTURA'] = df_factura_d['FACTURA']  # Mismo caso que en df_factura_d
        df_factura_v['EMISION'] = df_factura_d['EMISION']
        
        # Validación 3: Después de crear estructura base
        if len(df_factura_v) != original_count:
            logger.error(f"ERROR: Pérdida de registros al crear df_factura_v. Original: {original_count}, Actual: {len(df_factura_v)}")
            return False
        
        # Validación específica: FACTURA debe ser idéntica en ambos dataframes
        facturas_identicas = (df_factura_d['FACTURA'] == df_factura_v['FACTURA']).all()
        if not facturas_identicas:
            logger.error("ERROR: Las columnas FACTURA no son idénticas entre df_factura_d y df_factura_v")
            # Debug: mostrar diferencias
            for idx in range(min(len(df_factura_d), len(df_factura_v))):
                if df_factura_d.iloc[idx]['FACTURA'] != df_factura_v.iloc[idx]['FACTURA']:
                    logger.error(f"Diferencia en índice {idx}: df_factura_d='{df_factura_d.iloc[idx]['FACTURA']}', df_factura_v='{df_factura_v.iloc[idx]['FACTURA']}'")
            return False
        
        # Generar campos para cada registro
        sif_ids = []
        qr_base64s = []
        hashes = []
        previous_hashes = []
        xmls = []
        
        logger.info("Generando códigos y hashes...")
        processed_count = 0
        error_count = 0
        
        for idx, row in df_factura_d.iterrows():
            try:
                sif_ids.append(_gen_SIF_ID(row))
                qr_base64s.append(_gen_QR_BASE64(row))
                hashes.append(_gen_HASH(row))
                previous_hashes.append(_gen_PREVIOUS_HASH(df_factura_d, idx))
                processed_count += 1
                
                if idx % 10 == 0:
                    logger.info(f"Procesadas {idx+1}/{original_count} facturas")
                    
            except Exception as e:
                logger.error(f"Error procesando fila {idx} (Factura: {row['FACTURA']}): {e}")
                sif_ids.append("ERROR")
                qr_base64s.append("")
                hashes.append("")
                previous_hashes.append("")
                error_count += 1
        
        # Validación 4: Después de generar códigos y hashes
        if len(sif_ids) != original_count:
            logger.error(f"ERROR: Número incorrecto de SIF_IDs generados. Esperado: {original_count}, Generado: {len(sif_ids)}")
            return False
            
        df_factura_v['SIF_ID'] = sif_ids
        df_factura_v['QR_CODE'] = qr_base64s
        df_factura_v['QR_BASE64'] = qr_base64s
        df_factura_v['HASH'] = hashes
        df_factura_v['PREVIOUS_HASH'] = previous_hashes
        
        # Validación 5: Después de asignar todos los campos
        if len(df_factura_v) != original_count:
            logger.error(f"ERROR: Pérdida de registros después de asignar campos. Original: {original_count}, Actual: {len(df_factura_v)}")
            return False
        
        # Generar XMLs
        logger.info("Generando XMLs...")
        successful_xmls = 0
        xml_errors = 0
        
        for idx, row in df_factura_v.iterrows():
            try:
                # Combinar datos manteniendo el caso original de FACTURA
                combined_row = {**df_factura_d.iloc[idx].to_dict(), **row.to_dict()}
                xml_content = _gen_XML(combined_row)  # Aquí es donde se convierte a mayúsculas para el XML
                xmls.append(xml_content)
                successful_xmls += 1
                
                if idx % 5 == 0:
                    logger.info(f"Generados {idx+1}/{original_count} XMLs")
                    
            except Exception as e:
                logger.error(f"Error generando XML para fila {idx} (Factura: {row['FACTURA']}): {e}")
                xmls.append("")
                xml_errors += 1
        
        df_factura_v['XML'] = xmls
        
        # Validación 6: Final - después de generar todos los XMLs
        if len(df_factura_v) != original_count:
            logger.error(f"ERROR CRÍTICO: Pérdida final de registros. Original: {original_count}, Final: {len(df_factura_v)}")
            return False
        
        # Validación 7: FACTURA sigue siendo idéntica después de todo el procesamiento
        facturas_final_identicas = (df_factura_d['FACTURA'] == df_factura_v['FACTURA']).all()
        if not facturas_final_identicas:
            logger.error("ERROR: Las columnas FACTURA dejaron de ser idénticas después del procesamiento completo")
            return False
        
        # Guardar en base de datos usando df2tDB_verifactu de views_utils
        logger.info("Guardando en base de datos usando df2tDB_verifactu...")
        
        
        # Usar la función específica para Veri*Factu
        insert_result = vu.df2tDB_verifactu(df_factura_v, sqlite3_dbpath)
        
        # Validación 8: Verificar inserción en base de datos
        conn = sqlite3.connect(DB_PATH)
        count_result = pd.read_sql_query("SELECT COUNT(*) as count FROM dentfact_factura_v", conn)
        conn.close()
        
        db_count = count_result['count'].iloc[0]
        if db_count != original_count:
            logger.error(f"ERROR CRÍTICO: Inconsistencia en base de datos. Esperado: {original_count}, Encontrado: {db_count}")
            return False
        
        # Resumen final
        logger.info(f"PROCESAMIENTO COMPLETADO EXITOSAMENTE:")
        logger.info(f"  - Facturas originales: {original_count}")
        logger.info(f"  - Facturas procesadas: {processed_count}")
        logger.info(f"  - Errores en procesamiento: {error_count}")
        logger.info(f"  - XMLs generados exitosamente: {successful_xmls}")
        logger.info(f"  - Errores en XML: {xml_errors}")
        logger.info(f"  - Registros en tabla destino: {db_count}")
        logger.info(f"  - CONSISTENCIA: {original_count} = {db_count} ✓")
        logger.info(f"  - FACTURA idéntica en ambos dataframes: ✓")
        logger.info(f"  - Resultado inserción BD: {insert_result['inserted']} insertados, {insert_result['skipped']} omitidos")
        
        if insert_result['errors']:
            logger.warning(f"  - Errores en inserción BD: {len(insert_result['errors'])}")
            for error in insert_result['errors']:
                logger.warning(f"    - {error}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error en el proceso principal: {e}")
        return False

#####################################################################################################
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import base64, re, io, logging
import sqlite3
from PIL import Image
from pyzbar.pyzbar import decode as decode_qr

logger = logging.getLogger(__name__)

DB_PATH = Path(r"c:\data\dentfact.sqlite3")

# ---------------------------------------------------------------------
# VALIDACIÓN FACTURA VERI*FACTU
# ---------------------------------------------------------------------
@csrf_exempt
def validateFactura(request, facturaId):
    """
    Valida la factura Veri*Factu correspondiente a facturaId:
    - Verifica existencia en dentfact_factura_v.
    - Comprueba hash y SIF_ID.
    - Verifica coherencia de campos clave.
    """
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Método no permitido"}, status=405)

    try:
        factura_id = str(facturaId).strip()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        cur.execute("""
            SELECT FACTURA, SIF_ID, HASH, PREVIOUS_HASH, XML 
            FROM dentfact_factura_v 
            WHERE FACTURA = ?
        """, (factura_id,))
        row = cur.fetchone()
        conn.close()

        if not row:
            return JsonResponse({"status": "error", "message": f"No se encontró la factura {factura_id}"})

        factura, sif_id, hash_val, prev_hash, xml = row
        errors = []

        # --- Validación SIF_ID ---
        if not sif_id or not re.match(r'^SIF-[A-F0-9]{8,60}$', sif_id):
            errors.append("Identificador SIF_ID inválido")

        # --- Validación HASH ---
        if not hash_val or not re.match(r'^[0-9a-fA-F]{64}$', hash_val):
            errors.append("Hash inválido o no generado")

        # --- Validación XML ---
        if not xml or "<RegistroFacturacion" not in xml:
            errors.append("XML Veri*Factu ausente o incompleto")

        # --- Verificar integridad con tabla dentfact_factura_d ---
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query(
            "SELECT FACTURA, TOTAL_FACTURA, BASE_FACTURA, EMISION FROM dentfact_factura_d WHERE FACTURA = ?",
            conn, params=(factura_id,)
        )
        conn.close()

        if df.empty:
            errors.append("No existe registro en dentfact_factura_d para esta factura")

        # Si todo correcto
        if errors:
            logger.warning(f"Validación fallida para factura {factura_id}: {errors}")
            return JsonResponse({
                "status": "error",
                "message": "❌ Factura inválida:\n" + "\n".join(errors)
            })

        logger.info(f"Factura {factura_id} validada correctamente ✅")
        return JsonResponse({
            "status": "success",
            "message": f"✅ FACTURA {factura_id} VÁLIDA (Veri*Factu coherente)"
        })

    except Exception as e:
        logger.error(f"Error en validateFactura({facturaId}): {e}", exc_info=True)
        return JsonResponse({
            "status": "error",
            "message": f"Error al validar la factura: {e}"
        }, status=500)

# ---------------------------------------------------------------------
# VALIDACIÓN CÓDIGO QR VERI*FACTU
# ---------------------------------------------------------------------
@csrf_exempt
def validateQRCode(request, facturaId):
    """
    Verifica que el código QR de la factura sea decodificable
    y contenga un enlace Veri*Factu válido.
    """
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Método no permitido"}, status=405)

    try:
        factura_id = str(facturaId).strip()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT QR_BASE64 FROM dentfact_factura_v WHERE FACTURA = ?", (factura_id,))
        row = cur.fetchone()
        conn.close()

        if not row or not row[0]:
            return JsonResponse({"status": "error", "message": "Factura sin código QR"})

        qr_base64 = row[0].strip()

        # Detectar formato base64 válido
        if qr_base64.startswith("data:image"):
            qr_base64 = qr_base64.split(",")[1]

        qr_bytes = base64.b64decode(qr_base64)
        img = Image.open(io.BytesIO(qr_bytes))

        decoded = decode_qr(img)
        if not decoded:
            return JsonResponse({"status": "error", "message": "No se pudo decodificar el código QR"})

        qr_text = decoded[0].data.decode('utf-8')
        logger.info(f"QR decodificado para factura {factura_id}: {qr_text}")

        if not qr_text.startswith("https://sede.agenciatributaria.gob.es/"):
            return JsonResponse({
                "status": "error",
                "message": "El código QR no apunta a una URL Veri*Factu válida"
            })

        return JsonResponse({
            "status": "success",
            "message": "✅ Código QR Veri*Factu válido y decodificable"
        })

    except Exception as e:
        logger.error(f"Error en validateQRCode({facturaId}): {e}", exc_info=True)
        return JsonResponse({
            "status": "error",
            "message": f"Error al validar el código QR: {e}"
        }, status=500)


# =============================================================================
#  Generación del PDF de la factura (para envío por email)
# =============================================================================
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)


def _safe(v, default=''):
    """Devuelve '' para None y hace str del resto, sin tocar el formato."""
    if v is None:
        return default
    return str(v)


def generate_factura_pdf(factura) -> bytes:
    """
    Genera el PDF de una factura (objeto Factura_D) y devuelve los bytes.

    Pensado para adjuntarse en el correo que se envía al doctor (emisor).
    No pretende replicar pixel a pixel la plantilla HTML del dashboard,
    sino producir un A4 limpio y legible con todos los datos fiscales.
    """
    try:
        from io import BytesIO
    except ImportError:
        raise

    buffer = BytesIO()

    # -- Estilos -------------------------------------------------------------
    styles = getSampleStyleSheet()

    s_titulo = ParagraphStyle(
        'titulo', parent=styles['Title'],
        fontName='Helvetica-Bold', fontSize=20, leading=24,
        alignment=TA_LEFT, textColor=colors.HexColor('#1e293b'),
        spaceAfter=2,
    )
    s_seccion = ParagraphStyle(
        'seccion', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=9, leading=11,
        alignment=TA_LEFT, textColor=colors.HexColor('#3b82f6'),
        spaceBefore=2, spaceAfter=4,
    )
    s_label = ParagraphStyle(
        'label', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8.5, leading=11,
        textColor=colors.HexColor('#475569'),
    )
    s_valor = ParagraphStyle(
        'valor', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8.5, leading=11,
        textColor=colors.HexColor('#0f172a'),
    )
    s_valor_der = ParagraphStyle(
        'valor_der', parent=s_valor, alignment=TA_RIGHT,
    )
    s_total = ParagraphStyle(
        'total', parent=s_valor,
        fontName='Helvetica-Bold', fontSize=11, leading=14,
        alignment=TA_RIGHT, textColor=colors.HexColor('#1e293b'),
    )
    s_footer = ParagraphStyle(
        'footer', parent=styles['Normal'],
        fontName='Helvetica', fontSize=6.5, leading=9,
        alignment=TA_CENTER, textColor=colors.HexColor('#64748b'),
    )

    # -- Datos de la factura -------------------------------------------------
    factura_id     = _safe(getattr(factura, 'FACTURA', 'N/A'))
    emision        = _safe(getattr(factura, 'EMISION', ''))
    l_desde        = _safe(getattr(factura, 'L_DESDE', ''))
    l_hasta        = _safe(getattr(factura, 'L_HASTA', ''))

    doctor         = _safe(getattr(factura, 'DOCTOR', 'N/A'))
    dni            = _safe(getattr(factura, 'DNI', ''))
    email_emisor   = _safe(getattr(factura, 'EMAIL', ''))
    telefono       = _safe(getattr(factura, 'TELEFONO', ''))
    direccion      = _safe(getattr(factura, 'DIRECCION', ''))
    postal         = _safe(getattr(factura, 'POSTAL', ''))
    ciudad         = _safe(getattr(factura, 'CIUDAD', ''))

    sociedad       = _safe(getattr(factura, 'SOCIEDAD', 'N/A'))
    cif            = _safe(getattr(factura, 'CIF', ''))
    desc_soc       = _safe(getattr(factura, 'DESCRIPCION_SOC', ''))
    dir_soc        = _safe(getattr(factura, 'DIRECCION_SOC', ''))
    postal_soc     = _safe(getattr(factura, 'POSTAL_SOC', ''))
    provincia_soc  = _safe(getattr(factura, 'PROVINCIA_SOC', ''))

    calculo_total  = _safe(getattr(factura, 'CALCULO_TOTAL', '0,00 €'))
    gastos         = _safe(getattr(factura, 'GASTOS', '0,00 €'))
    base_factura   = _safe(getattr(factura, 'BASE_FACTURA', '0,00 €'))
    irpf           = _safe(getattr(factura, 'IRPF', '0,00%'))
    cuota_irpf     = _safe(getattr(factura, 'CUOTA_IRPF', '0,00 €'))
    total_factura  = _safe(getattr(factura, 'TOTAL_FACTURA', '0,00 €'))

    # -- Documento -----------------------------------------------------------
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f'Factura {factura_id}',
        author='DENTFACT',
        subject=f'Factura {factura_id}',
    )

    story = []

    # --- Cabecera -----------------------------------------------------------
    header_table = Table(
        [[
            Paragraph('FACTURA', s_titulo),
            Paragraph(
                '<font color="#ffffff" backColor="#10b981"><b> VERI*FACTU </b></font>',
                ParagraphStyle('badge', parent=s_valor_der, fontSize=9, leading=12)
            ),
        ]],
        colWidths=[120 * mm, 60 * mm],
    )
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(HRFlowable(
        width='100%', thickness=1,
        color=colors.HexColor('#3b82f6'),
        spaceBefore=2, spaceAfter=10,
    ))

    # --- Datos de la factura ------------------------------------------------
    datos_factura = [
        ['Nº Factura:', factura_id],
        ['Tipo:', 'F1 (Exenta de IVA *)'],
        ['Emisión:', emision],
        ['Periodo:', f'{l_desde} — {l_hasta}'],
        ['Forma de pago:', 'Transferencia bancaria'],
    ]
    tabla_datos = Table(
        [[Paragraph(a, s_label), Paragraph(b, s_valor)] for a, b in datos_factura],
        colWidths=[35 * mm, 145 * mm],
    )
    tabla_datos.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(tabla_datos)
    story.append(Spacer(1, 8 * mm))

    # --- Emisor / Receptor --------------------------------------------------
    def bloque(titulo, filas):
        data = [[Paragraph(titulo, s_seccion), '']]
        for k, v in filas:
            data.append([Paragraph(k, s_label), Paragraph(v or '—', s_valor)])
        t = Table(data, colWidths=[24 * mm, 64 * mm])
        t.setStyle(TableStyle([
            ('SPAN', (0, 0), (1, 0)),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#3b82f6')),
        ]))
        return t

    bloque_emisor = bloque('EMISOR', [
        ('Doctor:', doctor),
        ('DNI:', dni),
        ('Email:', email_emisor),
        ('Teléfono:', telefono),
        ('Dirección:', f'{direccion}, {postal}, {ciudad}'.strip(', ')),
    ])
    bloque_receptor = bloque('RECEPTOR', [
        ('Sociedad:', sociedad),
        ('Descripción:', desc_soc),
        ('CIF:', cif),
        ('Dirección:', f'{dir_soc}, {postal_soc}, {provincia_soc}'.strip(', ')),
    ])

    bloque_grid = Table(
        [[bloque_emisor, bloque_receptor]],
        colWidths=[88 * mm, 88 * mm],
    )
    bloque_grid.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(bloque_grid)
    story.append(Spacer(1, 8 * mm))

    # --- Detalle de importes ------------------------------------------------
    story.append(Paragraph('DETALLE DE IMPORTES', s_seccion))

    importes = [
        ['Cálculo Total:', calculo_total],
        ['Gastos:', gastos],
        ['Base Factura:', base_factura],
        [f'IRPF ({irpf}):', cuota_irpf],
        ['IVA (0,00%):', '0,00 €'],
    ]
    filas = [[Paragraph(k, s_label), Paragraph(v, s_valor_der)] for k, v in importes]

    tabla_importes = Table(filas, colWidths=[120 * mm, 56 * mm])
    tabla_importes.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LINEBELOW', (0, 0), (-1, -2), 0.3, colors.HexColor('#e2e8f0')),
    ]))
    story.append(tabla_importes)

    total_table = Table(
        [[
            Paragraph('<b>TOTAL FACTURA:</b>', s_valor),
            Paragraph(f'<b>{total_factura}</b>', s_total),
        ]],
        colWidths=[120 * mm, 56 * mm],
    )
    total_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEABOVE', (0, 0), (-1, 0), 1.2, colors.HexColor('#8b5cf6')),
        ('LINEBELOW', (0, 0), (-1, 0), 1.2, colors.HexColor('#8b5cf6')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#faf5ff')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(total_table)

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph('(*) Exenta de IVA según art. 20.1.5 de la Ley 37/1992', s_footer))
    story.append(Spacer(1, 8 * mm))

    # --- Pie ----------------------------------------------------------------
    story.append(HRFlowable(
        width='100%', thickness=0.6,
        color=colors.HexColor('#3b82f6'),
        spaceBefore=0, spaceAfter=4,
    ))
    story.append(Paragraph(
        'Factura generada por DENTFACT. VERI*FACTU, verificable en la sede electrónica de la AEAT.<br/>'
        'Cumple con la normativa de la Agencia Tributaria Española.',
        s_footer,
    ))

    # --- Build --------------------------------------------------------------
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes