# views_pdf.py
import os
import re
import logging
import configparser
import pandas as pd
import pdfplumber
from pathlib import Path
import sys
import argparse
from typing import Dict, Optional

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('dentfact_pdf.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Configurar entorno Django para modo standalone
if __name__ == "__main__":
    try:
        # Añadir directorio raíz del proyecto a sys.path
        project_root = Path(__file__).parent.parent.parent  # Subir a C:\dentfact
        sys.path.insert(0, str(project_root))
        
        # Configurar DJANGO_SETTINGS_MODULE
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
        
        # Inicializar Django
        import django
        django.setup()
        logger.info("Entorno Django configurado para modo standalone")
    except Exception as e:
        logger.error(f"Error al configurar Django en modo standalone: {e}")
        raise

# Importar views_utils después de configurar Django
try:
    from apps.home import views_utils as vu
except ImportError as e:
    logger.error(f"Error al importar views_utils: {e}")
    raise

# Leer configuración desde config.ini
def load_config(config_path: Optional[str] = None) -> Dict[str, str]:
    """Carga la configuración desde el archivo config.ini"""
    config = configparser.ConfigParser()
    
    # Resolver config_path dinámicamente
    if config_path is None:
        # Subir tres niveles desde views_pdf.py (C:\dentfact\apps\home) para llegar a C:\dentfact
        config_path = os.environ.get('CONFIG_PATH', str(Path(__file__).parent.parent.parent / 'config.ini'))
    
    config_path = Path(config_path)
    try:
        if not config_path.exists():
            raise FileNotFoundError(f"Archivo de configuración no encontrado: {config_path}")
        
        config.read(config_path, encoding='utf-8')
        
        # Obtener rutas de inputs, con fallbacks consistentes con settings.py
        pdf_path = config.get('inputs', 'pdf', fallback=str(Path('c:/data/pdf')))
        sqlite3_dbpath = config.get('outputs', 'sqlite3_dbpath', fallback=str(Path('c:/data/dentfact.sqlite3')))
        
        logger.info(f"Configuración cargada: PDF_PATH={pdf_path}, DB_PATH={sqlite3_dbpath}")
        
        return {
            'PDF_PATH': str(Path(pdf_path)),
            'SQLITE_DB_PATH': str(Path(sqlite3_dbpath))
        }
        
    except Exception as e:
        logger.error(f"Error al cargar configuración: {e}")
        return {
            'PDF_PATH': str(Path('c:/data/pdf')),
            'SQLITE_DB_PATH': str(Path('c:/data/dentfact.sqlite3'))
        }

# Cargar configuración al importar el módulo
CONFIG = load_config()
PDF_PATH = CONFIG['PDF_PATH']
SQLITE_DB_PATH = CONFIG['SQLITE_DB_PATH']

def cleanText(texto: str) -> list:
    """
    Limpia el texto extraído de los PDFs eliminando cadenas no deseadas.
    """
    cadenas_a_eliminar = [
        'Sanitas Nuevos Negocios S.L.U.', 
        'C/ Ribera del Loira, 5228042 Madrid', 
        '91 324 49 22',
        'Madrid',
        'B86331253', 
        'Tel.', 
        'C.I.F.',
        'CIF/NIF', 
        'CONCEPTO IMPORTES',
        'CLIENTE Nº LIQUIDACIÓN Nº FACTURA FECHA',
        'C/ Ribera del Loira, 52',
        '28042',
        'Euros',
        'MADRID',
        'TOTAL FACTURA',
        '(I.V.A. EXENTO)',
        'TOT AL FACTURAFactur a exenta de IV A según a rt 20.1.5 de la L ey 37/1992 de I VA. CLIENTE Nº LIQUIDACIÓN Nº FACTURA FECHACIF/NIF',
        'Factura exenta de IVA según art 20.1.5 de la Ley 37/1992 de IVA.', 
        'FACTURACION HHMM',
        'Honorarios correspondientes al mes de:'
    ]
    
    for cadena in cadenas_a_eliminar:
        texto = texto.replace(cadena, "")
    
    # Quitar líneas vacías o solo con espacios
    lineas = [linea.strip() for linea in texto.splitlines() if linea.strip()]
    return lineas

def readPDF(base_path: str) -> Optional[str]:
    """
    Lee todos los archivos PDF en el directorio base y subdirectorios.
    Extrae y limpia el texto de cada PDF.
    """
    base_path = Path(base_path)
    if not base_path.exists():
        logger.error(f"Directorio de PDFs no existe: {base_path}")
        return None

    converted_files = {}
    unconverted_files = {}
    all_texts = []
    
    for dirpath, dirnames, filenames in os.walk(base_path):
        converted_files[dirpath] = 0
        unconverted_files[dirpath] = 0
        
        for filename in filenames:
            if filename.endswith('.pdf'):
                pdf_path = os.path.join(dirpath, filename)
                try:
                    with pdfplumber.open(pdf_path) as pdf:
                        text = ''
                        for page in pdf.pages:
                            page_text = page.extract_text()
                            if page_text:
                                text += page_text + '\n'
                        
                        if text:
                            cleaned_text = cleanText(text)
                            if cleaned_text:
                                file_name_without_ext = os.path.splitext(filename)[0]
                                output_text = f"{file_name_without_ext}\n" + '\n'.join(cleaned_text)
                                all_texts.append(output_text)
                                converted_files[dirpath] += 1
                            else:
                                logger.warning(f"El archivo {filename} en {dirpath} no contiene texto después de la limpieza.")
                                unconverted_files[dirpath] += 1
                        else:
                            logger.warning(f"El archivo {filename} en {dirpath} no contiene texto extraíble.")
                            unconverted_files[dirpath] += 1
                except Exception as e:
                    logger.error(f"Error al procesar {filename} en {dirpath}: {e}")
                    unconverted_files[dirpath] += 1

    # Resumen de conversión
    logger.info("\nResumen de conversión por carpeta:")
    for dirpath in set(converted_files.keys()) | set(unconverted_files.keys()):
        logger.info(f"Carpeta: {dirpath}")
        logger.info(f"  Convertidos: {converted_files.get(dirpath, 0)}")
        logger.info(f"  No Convertidos: {unconverted_files.get(dirpath, 0)}")

    return '\n'.join(all_texts) if all_texts else None

def pdf2df(pdfText: Optional[str], sqlite3_dbpath: str) -> pd.DataFrame:
    """
    Convierte el texto de PDFs en un DataFrame y lo guarda en la base de datos.
    
    Args:
        pdfText: Texto extraído de los PDFs
        sqlite3_dbpath: Ruta de la base de datos SQLite
    
    Returns:
        pd.DataFrame: DataFrame con los datos procesados
    """
    try:
        if pdfText is None or not pdfText.strip():
            raise ValueError("El texto del PDF es None o está vacío. No se puede procesar.")
        
        lineas = pdfText.split('\n')
        
        columnas = [
            "FACTURA", "DESCRIPCION_SOC", "DIRECCION_SOC", "POSTAL_SOC", "CIF", 
            "DATA_1", "DATA_2", "CENTRO_N", "TOTAL"
        ]
        
        registros = []
        for i in range(0, len(lineas), 9):
            if i + 9 <= len(lineas):
                registro = lineas[i:i+9]
                if any(not linea.strip() for linea in registro):
                    logger.warning(f"Registro incompleto o con líneas vacías detectado en línea {i+1}")
                    continue
                registros.append(dict(zip(columnas, registro)))
            else:
                logger.warning(f"Registro incompleto detectado al final del documento en línea {i+1}")
        
        if not registros:
            logger.warning("No se encontraron registros válidos para crear el DataFrame.")
            return pd.DataFrame(columns=columnas)

        df = pd.DataFrame(registros, columns=columnas)
        
        # Extracción de datos específicos
        df['CENTRO'] = df['DATA_1'].apply(lambda x: re.search(r'C\d{3}', x).group() if re.search(r'C\d{3}', x) else '')
        df['FECHA'] = df['DATA_1'].str[-10:]
        df['PERIODO'] = df['DATA_2'].apply(lambda x: x[:7] if len(x) >= 7 else '')
        df['SUBTOTAL'] = df['DATA_2'].apply(lambda x: x[7:] if len(x) > 7 else '')

        keep_columns = ['FACTURA', 'FECHA', 'PERIODO', 'CIF', 'DESCRIPCION_SOC', 'DIRECCION_SOC', 
                        'POSTAL_SOC', 'CENTRO', 'CENTRO_N', 'SUBTOTAL', 'TOTAL']
        df_factura_r = df[keep_columns].copy()  # Crear copia explícita para evitar SettingWithCopyWarning

        # Validar que SUBTOTAL y TOTAL no estén vacíos
        for col in ['SUBTOTAL', 'TOTAL']:
            if df_factura_r[col].str.strip().eq('').any():
                logger.warning(f"Valores vacíos detectados en {col}: {df_factura_r[df_factura_r[col].str.strip() == ''][col].tolist()}")

        # Guardar en base de datos usando views_utils.df2tDB
        if not df_factura_r.empty:
            
            success = vu.df2tDB(df_factura_r, sqlite3_dbpath, 'FACTURA', 'dentfact_factura_r')
            if success:
                logger.info(f"Se han guardado {len(df_factura_r)} registros en dentfact_factura_r")
            else:
                logger.error("Error al guardar los registros en la base de datos.")
        else:
            logger.warning("El DataFrame resultante está vacío. No se guardó nada en la base de datos.")
        
        logger.info(f"Número de registros en el DataFrame: {len(df_factura_r)}")
        return df_factura_r

    except Exception as e:
        logger.error(f"Ha ocurrido un error en pdf2df: {str(e)}")
        raise

def get_factura_r(pdf_path: Optional[str] = None, db_path: Optional[str] = None) -> pd.DataFrame:
    """
    Ejecuta el proceso ETL para PDFs y pobla dentfact_factura_r.
    
    Args:
        pdf_path: Ruta de los archivos PDF (opcional, usa config por defecto)
        db_path: Ruta de la base de datos (opcional, usa config por defecto)
    
    Returns:
        pd.DataFrame: DataFrame con los datos de facturas procesados
    """
    try:
        logger.info("Inicio del proceso obtención de las facturas recibidas")
        
        # Usar valores de configuración si no se proporcionan parámetros
        if pdf_path is None:
            pdf_path = PDF_PATH
        if db_path is None:
            db_path = SQLITE_DB_PATH
            
        logger.info(f"Procesando PDFs desde: {pdf_path}")
        logger.info(f"Guardando en base de datos: {db_path}")
        
        # 1. Leer PDFs
        pdfText = readPDF(pdf_path)
        
        if pdfText is None or not pdfText.strip():
            logger.warning("El texto del PDF es None o está vacío. No se puede procesar.")
            return pd.DataFrame()

        # 2. Convertir a DataFrame y guardar en DB
        df_factura_r = pdf2df(pdfText, db_path)
        
        logger.info("Proceso de facturas recibidas completado exitosamente")
        return df_factura_r

    except Exception as e:
        logger.error(f"Error en get_factura_r: {str(e)}")
        raise

def init_pdf(pdf_path: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, any]:
    """
    Función principal para procesar PDFs y poblar dentfact_factura_r.
    Diseñada para ser invocada desde views.py o en modo standalone.
    
    Args:
        pdf_path: Ruta de los archivos PDF (opcional, usa config por defecto)
        db_path: Ruta de la base de datos (opcional, usa config por defecto)
    
    Returns:
        dict: Diccionario con estado, DataFrame y mensaje
              Ejemplo: {"success": True, "df": DataFrame, "message": "..."}
    """
    try:
        df_factura_r = get_factura_r(pdf_path, db_path)
        if df_factura_r is not None and not df_factura_r.empty:
            return {
                "success": True,
                "df": df_factura_r,
                "message": f"Procesados {len(df_factura_r)} registros y guardados en dentfact_factura_r"
            }
        else:
            return {
                "success": False,
                "df": None,
                "message": "No se generaron registros válidos para dentfact_factura_r"
            }
    except Exception as e:
        logger.error(f"Error en init_pdf: {str(e)}")
        return {
            "success": False,
            "df": None,
            "message": f"Error al procesar PDFs: {str(e)}"
        }

# Ejecución principal si se corre el script directamente
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Procesar PDFs de facturas recibidas y poblar dentfact_factura_r")
    parser.add_argument('--config_path', default=None, help="Ruta al archivo config.ini (opcional)")
    parser.add_argument('--pdf_path', default=CONFIG['PDF_PATH'], help="Ruta a la carpeta de PDFs")
    parser.add_argument('--db_path', default=CONFIG['SQLITE_DB_PATH'], help="Ruta a la base de datos SQLite")
    args = parser.parse_args()
    
    # Recargar config si se proporciona custom path
    if args.config_path:
        CONFIG = load_config(args.config_path)
        args.pdf_path = CONFIG['PDF_PATH']
        args.db_path = CONFIG['SQLITE_DB_PATH']
    
    result = init_pdf(args.pdf_path, args.db_path)
    if result["success"]:
        print(f"Proceso completado. {result['message']}")
        print(result["df"].head())
    else:
        print(f"Error: {result['message']}")