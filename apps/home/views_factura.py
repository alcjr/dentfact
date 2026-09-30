import os
import logging
import sqlite3
import locale
import datetime
from pathlib import Path
from configparser import ConfigParser
from typing import Optional, Dict, Any, Tuple

import numpy as np
import pandas as pd

from django.conf import settings

# Importar utilidades de la app (estas ya no hacen queries a nivel de módulo)
from apps.home import views_utils as vu
from apps.home import views_verifactu as vv


locale.setlocale(locale.LC_ALL, 'es_ES.UTF-8')
logger = logging.getLogger(__name__)
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

# --------------------------------------------------------------------
# FUNCIONES PRINCIPALES
# --------------------------------------------------------------------
def get_importes(tablas_path: Path, sqlite3_db: Path) -> pd.DataFrame:
    logger.info("Inicio get_importes. Ruta Excel: %s", tablas_path)
    try:
        excel_files = list(Path(tablas_path).rglob("*.xlsx"))
        if not excel_files:
            logger.warning("No se encontraron archivos Excel (.xlsx) en %s", tablas_path)
            return pd.DataFrame()
        logger.info("Archivos Excel encontrados: %s", [f.name for f in excel_files])

        df_raw = vu.xlsx2df(str(tablas_path))
        if df_raw is None or df_raw.empty:
            logger.warning("xlsx2df devolvió None o DataFrame vacío para %s", tablas_path)
            return pd.DataFrame()
        logger.info("Ficheros Excel leídos. Filas iniciales: %d, Columnas: %s", len(df_raw), list(df_raw.columns))

        df_renamed = vu.renCol(df_raw)
        if df_renamed is None or df_renamed.empty:
            logger.warning("renCol devolvió None o DataFrame vacío. Columnas esperadas no encontradas.")
            return pd.DataFrame()
        logger.info("Columnas renombradas. Filas: %d, Columnas: %s", len(df_renamed), list(df_renamed.columns))

        if 'L_HASTA' in df_renamed.columns:
            df_renamed['FECHA'] = df_renamed['L_HASTA']
            logger.info("Columna FECHA asignada desde L_HASTA.")
            try:
                df_renamed['ANNO'] = pd.to_datetime(df_renamed['L_HASTA'], format='%d/%m/%Y').dt.year
                logger.info("Columna ANNO generada a partir de L_HASTA.")
            except Exception as e:
                logger.warning("No se pudo derivar ANNO desde L_HASTA: %s. Añadiendo con None.", e)
                df_renamed['ANNO'] = None
        else:
            logger.warning("Columna L_HASTA no encontrada en df_renamed. FECHA y ANNO se establecerán como None.")
            df_renamed['FECHA'] = None
            df_renamed['ANNO'] = None

        df_sp = vu.addSPCODE(df_renamed)
        if df_sp is None or df_sp.empty:
            logger.warning("addSPCODE devolvió None o DataFrame vacío.")
            return pd.DataFrame()
        logger.info("SPCODE añadida. Filas: %d, Columnas: %s", len(df_sp), list(df_sp.columns))

        numeric_columns = [
            "PP_BASE", "PP_LIQUIDO", "PM_BASE", "PM_LIQUIDO", "P_BASE", "P_LIQUIDO",
            "R_BASE", "R_LIQUIDO", "C_FIJA", "C_TURNO", "PPA_BASE", "PPA_LIQUIDO",
            "PMA_BASE", "PMA_LIQUIDO", "PA_BASE", "PA_LIQUIDO", "HHRR", "BRUTO", "NETO"
        ]
        # Convertir columnas numéricas a texto
        for col in numeric_columns:
            df_sp[col] = df_sp[col].apply(lambda x: str(x) if pd.notnull(x) else '')
            if df_sp[col].isna().any():
                logger.warning(f"Valores nulos en {col}:\n{df_sp[df_sp[col].isna()][['L_HASTA', 'SPCODE', 'CENTRO', 'ESPECIALIDAD', col]].to_string()}")

        # Validar columnas de texto
        text_columns = [col for col in df_sp.columns if col not in numeric_columns]
        for col in text_columns:
            df_sp[col] = df_sp[col].map(lambda x: vu.clean_str(str(x)) if x is not None else '')
            if df_sp[col].isna().any():
                logger.warning(f"Valores nulos en {col} (texto):\n{df_sp[df_sp[col].isna()][['L_HASTA', 'SPCODE', 'CENTRO', 'ESPECIALIDAD', col]].to_string()}")

        # Eliminar duplicados estrictos
        dups = df_sp[df_sp.duplicated(keep=False)]
        if not dups.empty:
            logger.warning(f"Se encontraron {len(dups)} filas duplicadas estrictas en df_sp:\n{dups.to_string()}")
            df_sp = df_sp.drop_duplicates(keep='first')
            logger.info(f"Duplicados eliminados. Nuevo tamaño: {len(df_sp)} filas")
        else:
            logger.info("No se encontraron duplicados estrictos en df_sp.")

        # Log de todas las filas
        logger.debug(f"Contenido completo de df_sp:\n{df_sp.to_string()}")

        df_sp.to_csv(vPath / "df_importes_inDB.csv", index=False)
        try:
            result = vu.dfi2tdb(df_sp, db_path=str(sqlite3_db))
            logger.info(f"Datos guardados en dentfact_importes. Insertados: {result['inserted']}, Omitidos: {result['skipped']}, No insertados: {len(result['not_inserted'])}")
            if not result['not_inserted'].empty:
                logger.warning(f"Filas no insertadas (todas las columnas):\n{result['not_inserted'].to_string()}")
        except Exception as e:
            logger.error("Error al guardar en la base de datos con dfi2tdb: %s", e, exc_info=True)
            return pd.DataFrame()

        logger.info("get_importes completado: %d filas procesadas.", len(df_sp))
        return df_sp
    except Exception as e:
        logger.error("Error en get_importes: %s", e, exc_info=True)
        return pd.DataFrame()


def loadALL(sqlite3_dbpath):
    tablas = {
        "dentfact_importes": "df_importes",
        "dentfact_centro": "df_centro",
        "dentfact_especialidad": "df_especialidad",
        "dentfact_doctor": "df_doctor",
        "dentfact_docpercent": "df_docpercent",
        "dentfact_sociedad": "df_sociedad",
    }

    dataframes = {}
    try:
        logger.info("Inicio del proceso de carga de las tablas de datos...")
        for tabla, df_name in tablas.items():
            logger.info(f"Cargando datos de la tabla {tabla}.")
            try:
                df = vu.table2df(sqlite3_dbpath, tabla)
                if df is None or df.empty or not all(col in df.columns for col in ['ESPECIALIDAD', 'DESCRIPCION'] if tabla == 'dentfact_especialidad'):
                    logger.warning(f"La tabla {tabla} está vacía, no se pudo cargar o faltan columnas.")
                    if tabla == 'dentfact_especialidad':
                        df = pd.DataFrame(columns=['ESPECIALIDAD', 'DESCRIPCION'])
                        # Intentar poblar la tabla si está vacía
                        with sqlite3.connect(sqlite3_dbpath) as conn:
                            cursor = conn.cursor()
                            cursor.execute("SELECT COUNT(*) FROM dentfact_especialidad")
                            count = cursor.fetchone()[0]
                            if count == 0:
                                logger.info("Poblando dentfact_especialidad con datos de prueba.")
                                cursor.executemany(
                                    "INSERT OR IGNORE INTO dentfact_especialidad (ESPECIALIDAD, DESCRIPCION) VALUES (?, ?)",
                                    [('ORT', 'Ortodoncia'), ('END', 'Endodoncia')]
                                )
                                conn.commit()
                                df = pd.read_sql_query("SELECT * FROM dentfact_especialidad", conn)
                    else:
                        df = pd.DataFrame()
                else:
                    logger.info(f"Tabla {tabla} cargada correctamente con {len(df)} filas.")
                dataframes[df_name] = df
            except Exception as e:
                logger.error(f"Error al cargar la tabla {tabla}: {e}")
                if tabla == 'dentfact_especialidad':
                    dataframes[df_name] = pd.DataFrame(columns=['ESPECIALIDAD', 'DESCRIPCION'])
                else:
                    dataframes[df_name] = pd.DataFrame()
    except Exception as e:
        logger.error(f"Error general en loadALL: {e}")
        print(f"Error general al cargar las tablas: {e}")

    logger.info("Final del proceso de carga de las tablas de datos...")
    return dataframes

def merge_pi(df_factura_ri, df_docpercent):
    logger.info("Iniciando merge_pi()...")
    vIRPF = 0.15
    
    if df_docpercent.empty:
        logger.warning("Tabla dentfact_docpercent vacía. Usando valores por defecto.")
        df_merge = df_factura_ri.copy()
        df_merge['IRPF'] = vIRPF
        df_merge['PORCENTAJE'] = 0.0
        return df_merge
    
    df_factura_ri = df_factura_ri.copy()
    df_docpercent = df_docpercent.copy()
    
    for col in ['SPCODE', 'ESPECIALIDAD', 'CENTRO']:
        if col in df_factura_ri.columns:
            df_factura_ri[col] = df_factura_ri[col].apply(vu.clean_str)
        else:
            logger.warning(f"Columna {col} no encontrada en df_factura_ri. Añadiendo con valores vacíos.")
            df_factura_ri[col] = ""
    
    for col in ['SPCODE_id', 'ESPECIALIDAD', 'CENTRO']:
        if col in df_docpercent.columns:
            df_docpercent[col] = df_docpercent[col].apply(vu.clean_str)
        else:
            logger.warning(f"Columna {col} no encontrada en df_docpercent. Añadiendo con valores vacíos.")
            df_docpercent[col] = ""
    
    duplicates = df_docpercent.duplicated(subset=['SPCODE_id', 'ESPECIALIDAD', 'CENTRO'], keep=False)
    if duplicates.any():
        logger.warning(f"Se encontraron {duplicates.sum()} duplicados en df_docpercent. Tomando el último.")
        df_docpercent = df_docpercent.drop_duplicates(subset=['SPCODE_id', 'ESPECIALIDAD', 'CENTRO'], keep='last')
    
    df_docpercent['PORCENTAJE'] = pd.to_numeric(df_docpercent['PORCENTAJE'], errors='coerce')
    invalid_percent = df_docpercent[df_docpercent['PORCENTAJE'] > 1]
    if not invalid_percent.empty:
        logger.warning(f"Valores de PORCENTAJE > 1 encontrados en df_docpercent: {len(invalid_percent)} filas. Dividiendo por 100.")
        df_docpercent.loc[df_docpercent['PORCENTAJE'] > 1, 'PORCENTAJE'] /= 100
    
    df_merge = pd.merge(
        df_factura_ri,
        df_docpercent[['SPCODE_id', 'ESPECIALIDAD', 'CENTRO', 'IRPF', 'PORCENTAJE']],
        how='left',
        left_on=['SPCODE', 'ESPECIALIDAD', 'CENTRO'],
        right_on=['SPCODE_id', 'ESPECIALIDAD', 'CENTRO']
    )
    
    matched = df_merge['PORCENTAJE'].notna() & (df_merge['PORCENTAJE'] != 0.0)
    logger.info(f"Filas con coincidencias en merge: {matched.sum()}/{len(df_merge)}")
    if matched.sum() > 0:
        logger.debug(f"Ejemplo de coincidencias: {df_merge[matched][['SPCODE', 'ESPECIALIDAD', 'CENTRO', 'IRPF', 'PORCENTAJE']].head().to_dict()}")
    unmatched = ~matched
    if unmatched.sum() > 0:
        logger.debug(f"Ejemplo de no coincidencias: {df_merge[unmatched][['SPCODE', 'ESPECIALIDAD', 'CENTRO']].head().to_dict()}")
    
    df_merge['IRPF'] = df_merge['IRPF'].fillna(vIRPF)
    df_merge['PORCENTAJE'] = df_merge['PORCENTAJE'].fillna(0.0)
    df_merge = df_merge.drop(columns=['SPCODE_id'], errors='ignore')
    
    zero_percent = df_merge[df_merge['PORCENTAJE'] == 0]
    if not zero_percent.empty:
        log_filename = logs_dir / f"zero_porcentajes_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        log_filename.parent.mkdir(exist_ok=True)
        with open(log_filename, 'w', encoding='utf-8') as log_file:
            log_file.write("Registros con PORCENTAJE = 0 (para revisión y actualización)\n")
            log_file.write("=" * 60 + "\n")
            for idx, row in zero_percent.iterrows():
                log_file.write(f"SPCODE: {row['SPCODE']}, CENTRO: {row['CENTRO']}, ESPECIALIDAD: {row['ESPECIALIDAD']}\n")
            log_file.write(f"\nTotal de registros con PORCENTAJE = 0: {len(zero_percent)}\n")
        logger.info(f"Log generado para PORCENTAJE = 0: {log_filename}")
    
    logger.info(f"Merge_pi completado. Filas originales: {len(df_factura_ri)}, filas resultantes: {len(df_merge)}.")
    return df_merge

def merge_do(df_merge_pi, df_doctor):
    logger.info("Iniciando merge_do()...")
    if not isinstance(df_merge_pi, pd.DataFrame) or not isinstance(df_doctor, pd.DataFrame):
        raise ValueError("Ambos inputs deben ser DataFrames de pandas.")

    required_columns_pi = {'SPCODE', 'DOCTOR', 'ESPECIALIDAD', 'COLABORADOR', 'COLEGIADO', 'CENTRO', 'N_CENTRO', 'CIF', 'LIQUIDACION', 'L_DESDE', 'L_HASTA', 'HHRR', 'BRUTO', 'NETO', 'FECHA', 'IRPF', 'PORCENTAJE'}
    required_columns_doctor = {'SPCODE', 'COLEGIADO', 'DOCTOR', 'I_APELLIDO', 'II_APELLIDO', 'NOMBRE', 'DNI', 'CIF', 'GASTOS', 'ESTADO', 'EMAIL', 'DIRECCION', 'CIUDAD', 'POSTAL', 'TELEFONO', 'CUENTA', 'CODIGO', 'ESPECIALIDAD', 'COLABORADOR', 'GABINETE_01', 'GABINETE_02'}
    
    if not required_columns_pi.issubset(df_merge_pi.columns):
        logger.error(f"df_merge_pi debe contener: {required_columns_pi}")
        raise ValueError(f"df_merge_pi debe contener: {required_columns_pi}")
    if not required_columns_doctor.issubset(df_doctor.columns):
        logger.error(f"df_doctor debe contener: {required_columns_doctor}")
        raise ValueError(f"df_doctor debe contener: {required_columns_doctor}")

    df_merge_pi = df_merge_pi.copy()
    df_doctor = df_doctor.copy()
    
    duplicates = df_doctor.duplicated(subset=['SPCODE'], keep=False)
    if duplicates.any():
        logger.warning(f"Se encontraron {duplicates.sum()} duplicados en df_doctor para SPCODE.")
        df_doctor = df_doctor.drop_duplicates(subset=['SPCODE'], keep='last')
        logger.info(f"Después de eliminar duplicados, df_doctor tiene {len(df_doctor)} filas.")

    if df_merge_pi['SPCODE'].isna().any():
        logger.warning(f"Valores nulos en SPCODE de df_merge_pi:\n{df_merge_pi[df_merge_pi['SPCODE'].isna()][['DOCTOR', 'ESPECIALIDAD', 'CENTRO']].head().to_string()}")
        df_merge_pi['SPCODE'] = df_merge_pi['SPCODE'].fillna('')
    if df_doctor['SPCODE'].isna().any():
        logger.warning(f"Valores nulos en SPCODE de df_doctor:\n{df_doctor[df_doctor['SPCODE'].isna()][['DOCTOR', 'ESPECIALIDAD']].head().to_string()}")
        df_doctor['SPCODE'] = df_doctor['SPCODE'].fillna('')

    df_merge_do = df_merge_pi.merge(
        df_doctor,
        on='SPCODE',
        how='left',
        suffixes=('_pi', '_doctor')
    )

    for col in ['DOCTOR', 'ESPECIALIDAD', 'COLABORADOR', 'COLEGIADO', 'CIF']:
        if f'{col}_pi' in df_merge_do.columns and f'{col}_doctor' in df_merge_do.columns:
            df_merge_do = df_merge_do.drop(f'{col}_doctor', axis=1).rename(columns={f'{col}_pi': col})
        elif f'{col}_doctor' in df_merge_do.columns:
            df_merge_do = df_merge_do.rename(columns={f'{col}_doctor': col})

    if 'CODIGO' in df_merge_do.columns:
        df_merge_do = df_merge_do.drop('CODIGO', axis=1)

    expected_columns = [
        'SPCODE', 'DOCTOR', 'ESPECIALIDAD', 'COLABORADOR', 'COLEGIADO', 'CENTRO', 'N_CENTRO', 'CIF',
        'LIQUIDACION', 'L_DESDE', 'L_HASTA', 'HHRR', 'BRUTO', 'NETO', 'FECHA', 'IRPF', 'PORCENTAJE',
        'GASTOS', 'I_APELLIDO', 'II_APELLIDO', 'NOMBRE', 'DNI', 'ESTADO', 'EMAIL',
        'DIRECCION', 'CIUDAD', 'POSTAL', 'TELEFONO', 'CUENTA', 'GABINETE_01', 'GABINETE_02'
    ]
    for col in expected_columns:
        if col not in df_merge_do.columns:
            df_merge_do[col] = pd.NA
    df_merge_do = df_merge_do[expected_columns]

    registros_pi = len(df_merge_pi)
    registros_doctor = len(df_doctor)
    registros_cruzados = df_merge_do['NOMBRE'].notna().sum()
    registros_no_cruzados = df_merge_do['NOMBRE'].isna().sum()
    registros_fallidos = df_merge_do[df_merge_do['NOMBRE'].isna()][['SPCODE', 'DOCTOR', 'ESPECIALIDAD']]

    logger.info(f"Número de registros en df_merge_pi: {registros_pi}")
    logger.info(f"Número de registros en df_doctor: {registros_doctor}")
    logger.info(f"Registros cruzados con éxito: {registros_cruzados}")
    logger.info(f"Registros no cruzados: {registros_no_cruzados}")
    if not registros_fallidos.empty:
        logger.info(f"Registros no cruzados:\n{registros_fallidos.to_string(index=False)}")

    logger.info("Final del proceso de cruce de datos entre df_merge_pi y df_doctor.")
    return df_merge_do

def merge_so(df_merge_do, df_sociedad):
    try:
        logger.info("Inicio del proceso de cruce de datos entre df_merge_do y df_sociedad.")
        if not isinstance(df_merge_do, pd.DataFrame) or not isinstance(df_sociedad, pd.DataFrame):
            raise ValueError("Ambos inputs deben ser DataFrames de pandas.")
        
        required_columns_factura = {'CIF'}
        required_columns_sociedad = {'CIF', 'SOCIEDAD', 'DESCRIPCION_SOC', 'DIRECCION_SOC', 'POSTAL_SOC', 'PROVINCIA_SOC', 'REPRESENTANTE', 'NIF_REP'}
        
        if not required_columns_factura.issubset(df_merge_do.columns):
            raise ValueError(f"El DataFrame df_merge_do debe contener las columnas: {required_columns_factura}")
        if not required_columns_sociedad.issubset(df_sociedad.columns):
            raise ValueError(f"El DataFrame df_sociedad debe contener las columnas: {required_columns_sociedad}")
        
        df_merge_do['CIF'] = df_merge_do['CIF'].str.strip().str.upper()
        df_sociedad['CIF'] = df_sociedad['CIF'].str.strip().str.upper()
        
        df_merge_so = df_merge_do.merge(df_sociedad, on='CIF', how='left', suffixes=('_do', '_sociedad'))
        
        if 'SOCIEDAD_do' in df_merge_so.columns and 'SOCIEDAD_sociedad' in df_merge_so.columns:
            df_merge_so = df_merge_so.drop('SOCIEDAD_do', axis=1).rename(columns={'SOCIEDAD_sociedad': 'SOCIEDAD'})
        elif 'SOCIEDAD_sociedad' in df_merge_so.columns:
            df_merge_so = df_merge_so.rename(columns={'SOCIEDAD_sociedad': 'SOCIEDAD'})
        
        required_for_factura = ['SOCIEDAD', 'CENTRO', 'SPCODE', 'ESPECIALIDAD', 'L_HASTA']
        missing_cols = [col for col in required_for_factura if col not in df_merge_so.columns]
        if missing_cols:
            logger.error(f"Columnas faltantes para generar FACTURA: {missing_cols}")
            return pd.DataFrame()
        
        for col in required_for_factura:
            if df_merge_so[col].isna().any():
                logger.warning(f"Valores nulos en {col} para generar FACTURA:\n{df_merge_so[df_merge_so[col].isna()][['SPCODE', 'CENTRO', 'ESPECIALIDAD']].head().to_string()}")
                df_merge_so[col] = df_merge_so[col].fillna('')
        
        vDate = pd.to_datetime(df_merge_so['L_HASTA'], format='%d/%m/%Y', errors='coerce').dt.strftime('%d%m%y').fillna('000000')
        vEspecilidad = df_merge_so['ESPECIALIDAD'].str[:3].fillna('XXX')
        df_merge_so['FACTURA'] = (df_merge_so['SOCIEDAD'] + '-' + 
                          df_merge_so['CENTRO'] + '-' + 
                          df_merge_so['SPCODE'] + '-' + 
                          vEspecilidad + '-' + 
                          vDate + '-' + 
                          df_merge_so.index.astype(str))
        
        if df_merge_so['FACTURA'].duplicated().any():
            logger.error(f"Duplicados detectados en FACTURA:\n{df_merge_so[df_merge_so['FACTURA'].duplicated()][['FACTURA', 'SPCODE', 'CENTRO', 'ESPECIALIDAD']].head().to_string()}")
            return pd.DataFrame()
        
        columnas_finales = ['FACTURA', 'L_DESDE', 'L_HASTA', 'SPCODE', 'DOCTOR', 
                            'ESPECIALIDAD', 'COLABORADOR', 'COLEGIADO',
                            'I_APELLIDO', 'II_APELLIDO', 'NOMBRE', 'DNI', 'ESTADO', 'EMAIL', 'DIRECCION', 'CIUDAD', 'POSTAL', 'TELEFONO', 
                            'CUENTA', 'CENTRO', 'N_CENTRO', 'SOCIEDAD', 'CIF', 'DESCRIPCION_SOC', 'DIRECCION_SOC', 'POSTAL_SOC', 
                            'PROVINCIA_SOC', 'REPRESENTANTE', 'NIF_REP', 'LIQUIDACION', 'HHRR', 'NETO', 'BRUTO', 
                            'PORCENTAJE', 'GASTOS', 'IRPF']
        
        df_merge_so = df_merge_so.reindex(columns=columnas_finales, fill_value='')
        
        registros_factura = len(df_merge_do)
        registros_sociedad = len(df_sociedad)
        registros_cruzados = df_merge_so['DESCRIPCION_SOC'].notna().sum()
        registros_no_cruzados = df_merge_so['DESCRIPCION_SOC'].isna().sum()
        registros_fallidos = df_merge_so[df_merge_so['DESCRIPCION_SOC'].isna()][['CIF']]
        
        logger.info(f"Número de registros en df_merge_do: {registros_factura}")
        logger.info(f"Número de registros en df_sociedad: {registros_sociedad}")
        logger.info(f"Registros cruzados con éxito: {registros_cruzados}")
        logger.info(f"Registros no cruzados: {registros_no_cruzados}")
        if not registros_fallidos.empty:
            logger.info(f"Relación de registros no cruzados:\n{registros_fallidos.to_string(index=False)}")
        
        logger.info("Final del proceso de cruce de datos entre df_merge_do y df_sociedad.")
        return df_merge_so
    
    except Exception as e:
        logger.error(f"Error en merge_so: {str(e)}")
        return pd.DataFrame()
###########################################################################################################
def df_factura_cal(df_factura_c: pd.DataFrame) -> pd.DataFrame:
    """
    Realiza cálculos financieros para la tabla de facturas, generando la columna CALCULO.

    Esta función calcula la columna CALCULO según las siguientes reglas:
    - Si HHRR != 0 y HHRR != 100: CALCULO = BRUTO * PORCENTAJE
    - Si HHRR == 100: CALCULO = BRUTO - ((BRUTO * GABINETE_01) + (BRUTO * GABINETE_01 * vIVA))
    - Si HHRR == 0: CALCULO = 0.0
    Maneja valores nulos o cero en GABINETE_01 reemplazándolos por vGP (porcentaje de gabinete por defecto).
    Valida y limpia las columnas numéricas y de texto para compatibilidad con SQLite. Asegura que los valores
    de porcentaje (vGP, vIVA, GABINETE_01) se conviertan correctamente a decimales (ej. 11,5% → 0.115).

    Args:
        df_factura_c (pd.DataFrame): DataFrame con los datos de facturas que incluye columnas
            como BRUTO, NETO, PORCENTAJE, IRPF, GASTOS, HHRR, GABINETE_01, entre otras.

    Returns:
        pd.DataFrame: DataFrame procesado con la columna CALCULO calculada y columnas validadas.

    Raises:
        ValueError: Si df_factura_c no es un DataFrame, está vacío o faltan columnas requeridas.
        Exception: Para otros errores inesperados durante el procesamiento.
    """
    try:
        logger.info("Iniciando cálculos para df_factura_cal...")

        # Validaciones iniciales
        if not isinstance(df_factura_c, pd.DataFrame):
            logger.error(f"df_factura_c no es un DataFrame de pandas, tipo recibido: {type(df_factura_c)}")
            raise ValueError("df_factura_c debe ser un DataFrame de pandas")
        if df_factura_c.empty:
            logger.error("df_factura_c está vacío")
            raise ValueError("df_factura_c no puede estar vacío")

        required_columns = ['BRUTO', 'NETO', 'PORCENTAJE', 'IRPF', 'GASTOS', 'HHRR', 'GABINETE_01']
        missing_columns = set(required_columns) - set(df_factura_c.columns)
        if missing_columns:
            logger.error(f"Faltan columnas requeridas en df_factura_c: {missing_columns}")
            raise ValueError(f"Faltan columnas requeridas en df_factura_c: {missing_columns}")

        df = df_factura_c.copy()

        # Convertir vGP y vIVA a decimales
        def convert_percentage(value):
            try:
                # Convertir a string, limpiar símbolos y reemplazar coma por punto
                value_str = str(value).replace('%', '').replace(',', '.').strip()
                val = float(value_str)
                # Dividir por 100 si es un porcentaje (> 1 o formato típico de porcentaje)
                return val / 100 if val > 1 else val
            except (ValueError, TypeError):
                logger.warning(f"No se pudo convertir {value} a porcentaje, usando valor por defecto.")
                return 0.0

        global vGP, vIVA
        vGP = convert_percentage(vGP)
        vIVA = convert_percentage(vIVA)
        logger.info(f"Valores convertidos: vGP={vGP}, vIVA={vIVA}")

        # Convertir columnas numéricas
        numeric_columns = ['BRUTO', 'NETO', 'PORCENTAJE', 'IRPF', 'GASTOS', 'HHRR']
        for col in numeric_columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).replace('[€%]', '', regex=True).replace(',', '.', regex=True),
                errors='coerce'
            ).fillna(0.0)

        # Manejo de GABINETE_01
        if 'GABINETE_01' not in df.columns or df['GABINETE_01'].isna().all():
            df['GABINETE_01'] = vGP
            logger.info(f"Columna GABINETE_01 establecida a vGP={vGP} (columna ausente o completamente nula).")
        else:
            df['GABINETE_01'] = pd.to_numeric(
                df['GABINETE_01'].astype(str).replace('[€%]', '', regex=True).replace(',', '.', regex=True),
                errors='coerce'
            ).fillna(vGP)
            # Convertir valores de porcentaje a decimales (dividir por 100 si son > 1)
            df['GABINETE_01'] = df['GABINETE_01'].apply(lambda x: x / 100 if x > 1 else x)
            zeros_replaced = (df['GABINETE_01'] == 0).sum()
            df.loc[df['GABINETE_01'] == 0, 'GABINETE_01'] = vGP
            logger.info(f"Reemplazados {zeros_replaced} valores de GABINETE_01 que eran 0 o NaN por vGP={vGP}.")
        
        # Log para inspeccionar GABINETE_01 antes de los cálculos
        logger.debug(f"Valores de GABINETE_01 después de conversión:\n{df[['FACTURA', 'GABINETE_01']].to_string()}")

        # Inicializar CALCULO
        if 'CALCULO' not in df.columns:
            df['CALCULO'] = 0.0

        # Máscaras para cálculos
        mask_hhrr_not_zero = df['HHRR'] != 0
        logger.info(f"Número de filas con HHRR != 0: {mask_hhrr_not_zero.sum()}")
        mask_hhrr_100 = df['HHRR'] == 100
        mask_hhrr_not_100 = mask_hhrr_not_zero & ~mask_hhrr_100
        logger.info(f"Número de filas con HHRR == 100: {mask_hhrr_100.sum()}")
        logger.info(f"Número de filas con HHRR != 0 y HHRR != 100: {mask_hhrr_not_100.sum()}")

        # Cálculos
        df.loc[mask_hhrr_not_100, 'CALCULO'] = df.loc[mask_hhrr_not_100, 'BRUTO'] * df.loc[mask_hhrr_not_100, 'PORCENTAJE']
        df.loc[mask_hhrr_100, 'CALCULO'] = df.loc[mask_hhrr_100, 'BRUTO'] - (
            (df.loc[mask_hhrr_100, 'BRUTO'] * df.loc[mask_hhrr_100, 'GABINETE_01']) +
            (df.loc[mask_hhrr_100, 'BRUTO'] * df.loc[mask_hhrr_100, 'GABINETE_01'] * vIVA)
        )

        # Log para inspeccionar CALCULO para HHRR == 100
        logger.debug(f"Valores de CALCULO para HHRR == 100:\n{df[mask_hhrr_100][['FACTURA', 'BRUTO', 'GABINETE_01', 'CALCULO']].to_string()}")

        # Asegurar valores por defecto para IRPF y GASTOS
        df['IRPF'] = df['IRPF'].fillna(vIRPF)
        df['GASTOS'] = df['GASTOS'].fillna(vGASTOS)

        # Definir columnas esperadas
        expected_columns = [
            'FACTURA', 'L_DESDE', 'L_HASTA', 'SPCODE', 'DOCTOR', 'ESPECIALIDAD',
            'COLABORADOR', 'COLEGIADO', 'CENTRO', 'N_CENTRO', 'SOCIEDAD', 'CIF',
            'I_APELLIDO', 'II_APELLIDO', 'NOMBRE', 'DNI', 'ESTADO', 'EMAIL', 'DIRECCION', 'CIUDAD', 'POSTAL', 'TELEFONO', 
            'DESCRIPCION_SOC', 'DIRECCION_SOC', 'POSTAL_SOC', 'PROVINCIA_SOC',
            'REPRESENTANTE', 'NIF_REP', 'LIQUIDACION', 'HHRR', 'NETO', 'BRUTO',
            'PORCENTAJE', 'GASTOS', 'IRPF', 'CALCULO'
        ]
        for col in expected_columns:
            if col not in df.columns:
                df[col] = ''
                logger.warning(f"Columna {col} no encontrada en df_factura_c, añadida con valores vacíos")

        # Asegurar tipos numéricos
        for col in ['BRUTO', 'NETO', 'GASTOS', 'HHRR', 'PORCENTAJE', 'IRPF', 'GABINETE_01', 'CALCULO']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

        # Limpiar columnas de texto
        text_columns = [
            'FACTURA', 'L_DESDE', 'L_HASTA', 'SPCODE', 'DOCTOR', 'ESPECIALIDAD',
            'COLABORADOR', 'COLEGIADO', 'CENTRO', 'N_CENTRO', 'SOCIEDAD', 'CIF',
            'DESCRIPCION_SOC', 'DIRECCION_SOC', 'POSTAL_SOC', 'PROVINCIA_SOC',
            'REPRESENTANTE', 'NIF_REP', 'LIQUIDACION'
        ]
        for col in text_columns:
            if col in df.columns:
                df[col] = df[col].map(lambda x: vu.clean_str(str(x)) if pd.notnull(x) else '')

        # Validar salida
        if not isinstance(df, pd.DataFrame):
            logger.error("df_factura_cal no devolvió un DataFrame de pandas")
            raise ValueError("df_factura_cal debe devolver un DataFrame de pandas")

        logger.debug(f"Muestra de df_factura_c tras cálculos:\n{df[expected_columns].head().to_string()}")
        return df

    except Exception as e:
        logger.error(f"Error en df_factura_cal: {e}", exc_info=True)
        raise

################################################################################################################
def get_factura_c(db_path: str, table_name: str, pk_field: str, df_table: pd.DataFrame) -> pd.DataFrame:
    r"""Procesa facturas y las inserta en la base de datos.

    Genera la columna FACTURA con el formato SPCODE-CENTRO-ESPECIALIDAD[:4]-L_HASTA-INDEX.
    Llama a df_factura_cal para realizar cálculos en el DataFrame.
    Guarda los resultados en la tabla especificada en la base de datos.

    Args:
        db_path (str): Ruta a la base de datos SQLite.
        table_name (str): Nombre de la tabla destino (ej. dentfact_factura_c).
        pk_field (str): Nombre del campo de clave primaria (ej. FACTURA).
        df_table (pd.DataFrame): DataFrame con datos de facturas a procesar.

    Returns:
        pd.DataFrame: DataFrame procesado con cálculos y columnas validadas.

    Raises:
        ValueError: Si faltan columnas requeridas, el DataFrame está vacío o no es un DataFrame válido.
        sqlite3.Error: Si hay errores al interactuar con la base de datos.
    """
    logger = logging.getLogger(__name__)
    logger.info("Iniciando generación de facturas por centros...")
    try:
        # Validar que df_table es un DataFrame válido
        if not isinstance(df_table, pd.DataFrame):
            logger.error(f"df_table no es un DataFrame de pandas, tipo recibido: {type(df_table)}")
            raise ValueError("df_table debe ser un DataFrame de pandas")
        if df_table.empty:
            logger.error("df_table está vacío")
            raise ValueError("df_table no puede estar vacío")

        logger.info(f"Columnas en df_table: {list(df_table.columns)}")
        logger.info(f"Filas iniciales en df_table: {len(df_table)}")
        logger.info(f"Tipo de índice: {type(df_table.index)}")

        # Reiniciar el índice para asegurar que INDEX sea numérico
        df_table = df_table.reset_index(drop=True)
        logger.info("Índice reiniciado para garantizar unicidad en FACTURA.")

        # Validar datos de entrada
        required_columns = [
            'FACTURA', 'L_DESDE', 'L_HASTA', 'SPCODE', 'DOCTOR', 'ESPECIALIDAD',
            'COLABORADOR', 'COLEGIADO', 'CENTRO', 'N_CENTRO', 'SOCIEDAD', 'CIF',
            'I_APELLIDO', 'II_APELLIDO', 'NOMBRE', 'DNI', 'ESTADO', 'EMAIL', 'DIRECCION', 'CIUDAD', 'POSTAL', 'TELEFONO', 
            'DESCRIPCION_SOC', 'DIRECCION_SOC', 'POSTAL_SOC', 'PROVINCIA_SOC',
            'REPRESENTANTE', 'NIF_REP', 'LIQUIDACION', 'HHRR', 'NETO', 'BRUTO',
            'PORCENTAJE', 'GASTOS', 'IRPF', 'GABINETE_01', 'GABINETE_02', 'CALCULO'
        ]
        for col in required_columns:
            if col not in df_table.columns:
                df_table[col] = ''
            df_table[col] = df_table[col].map(lambda x: vu.clean_str(str(x)) if pd.notnull(x) else '')
            if df_table[col].isna().any():
                logger.warning(f"Valores nulos en {col}:\n{df_table[df_table[col].isna()][['SPCODE', 'ESPECIALIDAD', 'CENTRO', col]].to_string()}")

        # Convertir columnas numéricas antes de los cálculos
        numeric_columns = ['BRUTO', 'NETO', 'PORCENTAJE', 'IRPF', 'GASTOS', 'HHRR', 'GABINETE_01', 'GABINETE_02', 'CALCULO']
        for col in numeric_columns:
            if col in df_table.columns:
                df_table[col] = pd.to_numeric(
                    df_table[col].astype(str).replace('[€%]', '', regex=True).replace(',', '.', regex=True),
                    errors='coerce'
                ).fillna(0.0)

        # Realizar cálculos
        logger.info("Llamando a df_factura_cal...")
        df_table = df_factura_cal(df_table)
        df_table.to_csv(vPath/"df_factura_cal.csv", index=False)  # Guardar para depuración
        
        # Verificar que df_table sigue siendo un DataFrame después de df_factura_cal
        if not isinstance(df_table, pd.DataFrame):
            logger.error(f"df_factura_cal no devolvió un DataFrame de pandas, tipo recibido: {type(df_table)}")
            raise ValueError("df_factura_cal debe devolver un DataFrame de pandas")
        logger.info(f"Columnas después de df_factura_cal: {list(df_table.columns)}")
        logger.info(f"Filas después de df_factura_cal: {len(df_table)}")
        logger.info(f"Tipo de índice después de df_factura_cal: {type(df_table.index)}")

        # Generar FACTURA si no existe o está vacía
        if 'FACTURA' not in df_table.columns or df_table['FACTURA'].isna().all() or (df_table['FACTURA'] == '').all():
            # Asegurar que L_HASTA sea válido
            df_table['L_HASTA'] = df_table['L_HASTA'].fillna('01/01/2000')
            # Asegurar que las columnas necesarias estén limpias
            for col in ['SPCODE', 'CENTRO', 'ESPECIALIDAD', 'L_HASTA']:
                df_table[col] = df_table[col].map(lambda x: vu.clean_str(str(x)) if pd.notnull(x) else '')
            # Limitar ESPECIALIDAD a los primeros 4 caracteres
            df_table['ESPECIALIDAD_TRUNC'] = df_table['ESPECIALIDAD'].str[:4]
            # Generar FACTURA como SPCODE-CENTRO-ESPECIALIDAD[:4]-L_HASTA-INDEX
            df_table['FACTURA'] = (
                df_table['CENTRO'].astype(str) + '-' +
                df_table['SPCODE'].astype(str) + '-' +
                df_table['ESPECIALIDAD_TRUNC'].astype(str) + '-' +
                df_table['SOCIEDAD'].astype(str) + '-' +
                df_table['L_HASTA'].astype(str) + '-' +
                df_table.index.astype(str)
            )
            # Eliminar columna temporal ESPECIALIDAD_TRUNC
            df_table = df_table.drop(columns=['ESPECIALIDAD_TRUNC'], errors='ignore')
            logger.info("Columna FACTURA generada como SPCODE-CENTRO-ESPECIALIDAD[:4]-L_HASTA-INDEX.")
            logger.debug(f"Muestra de FACTURA: {df_table['FACTURA'].head().to_list()}")

        # Filtrar columnas para incluir solo las esperadas por dentfact_factura_c
        df_table = df_table[required_columns]
        logger.info(f"Columnas filtradas antes de vu.df2tDB: {list(df_table.columns)}")

        # Verificar que df_table es un DataFrame antes de guardar
        if not isinstance(df_table, pd.DataFrame):
            logger.error(f"df_table no es un DataFrame antes de llamar a vu.df2tDB, tipo recibido: {type(df_table)}")
            raise ValueError("df_table debe ser un DataFrame antes de guardar en la base de datos")

        # Guardar en la base de datos
        logger.info(f"Guardando {len(df_table)} filas en la tabla {table_name}...")
        result = vu.df2tDB(df_table, db_path, pk_field, table_name)
        if not result:
            logger.error(f"Fallo al guardar datos en la tabla {table_name}")
            raise ValueError(f"Error al guardar datos en {table_name}")
        logger.info(f"Datos guardados en {table_name}. Insertados: {result.get('inserted', 0)}, Omitidos: {result.get('skipped', 0)}")

        logger.info(f"Filas procesadas por get_factura_c: {len(df_table)}")
        return df_table

    except ValueError as ve:
        logger.error(f"Error de validación en get_factura_c: {ve}", exc_info=True)
        raise
    except sqlite3.Error as se:
        logger.error(f"Error de base de datos en get_factura_c: {se}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Error inesperado en get_factura_c: {e}", exc_info=True)
        raise
###########################################################################################################
# PARCHE COMPLETO: get_factura_d + init_factura
# =====================================================================
# Aplica este parche en views_factura.py
# Objetivo: 
#   1. Evitar UnicodeDecodeError (byte 0x90)
#   2. No bloquear VeriFactu si falla get_factura_d
#   3. Usar df_factura_c como fallback
# =====================================================================

# ---------------------------------------------------------------------
# 1. get_factura_d (VERSIÓN ROBUSTA CON LIMPIEZA UTF-8)
# ---------------------------------------------------------------------
def get_factura_d(df_factura_c: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Procesa df_factura_c → genera dentfact_factura_d.
    Incluye limpieza de codificación para evitar byte 0x90 (Windows-1252).
    """
    try:
        logger.info("Inicio del proceso get_factura_d.")

        # -----------------------------------------------------------------
        # LIMPIEZA DE CODIFICACIÓN: Convierte cualquier byte no UTF-8
        # -----------------------------------------------------------------
        def safe_clean(x):
            if pd.isna(x):
                return ''
            if isinstance(x, (str, bytes)):
                s = str(x)
                # Intenta UTF-8, si falla → latin1 → replace
                try:
                    return s.encode('utf-8', errors='strict').decode('utf-8')
                except:
                    try:
                        return s.encode('latin1', errors='replace').decode('utf-8', errors='replace')
                    except:
                        return s.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
            return str(x)

        # Aplica a TODAS las columnas object
        object_cols = df_factura_c.select_dtypes(include=['object']).columns
        for col in object_cols:
            df_factura_c[col] = df_factura_c[col].apply(safe_clean)
            # Log si detecta byte problemático
            if df_factura_c[col].str.contains(r'[\x00-\x1F\x7F-\x9F]', regex=True, na=False).any():
                bad_rows = df_factura_c[df_factura_c[col].str.contains(r'[\x00-\x1F\x7F-\x9F]', regex=True, na=False)]
                logger.warning(f"Bytes raros detectados en {col} (post-limpieza): {len(bad_rows)} filas")

        # -----------------------------------------------------------------
        # Cargar configuración (DD_FEMISION)
        # -----------------------------------------------------------------
        # Usar la clase ConfigParser importada arriba (from configparser import ConfigParser)
        config = ConfigParser()
        config_path = r'C:\dentfact\config.ini'
        if not config.read(config_path, encoding='utf-8'):
            logger.warning(f"config.ini no encontrado en {config_path}. Usando DD_FEMISION=21")
            DD_FEMISION = 21
        else:
            DD_FEMISION = config.getint('default', 'DD_FEMISION', fallback=21)

        # -----------------------------------------------------------------
        # Validaciones iniciales
        # -----------------------------------------------------------------
        required = ['SPCODE', 'BRUTO', 'PORCENTAJE', 'GASTOS', 'L_HASTA', 'SOCIEDAD', 'L_DESDE']
        missing = [c for c in required if c not in df_factura_c.columns]
        if missing:
            raise ValueError(f"Columnas faltantes: {', '.join(missing)}")
        if df_factura_c.empty:
            raise ValueError("df_factura_c está vacío.")

        df = df_factura_c.copy()

        # -----------------------------------------------------------------
        # Conversión numérica segura
        # -----------------------------------------------------------------
        for col in ['BRUTO', 'CALCULO', 'GASTOS']:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(r'[€%]', '', regex=True).str.replace(',', '.'),
                    errors='coerce'
                ).fillna(0.0)

        # IRPF
        if 'IRPF' not in df.columns:
            df['IRPF'] = vIRPF
        else:
            df['IRPF'] = pd.to_numeric(
                df['IRPF'].astype(str).str.replace('%', '').str.replace(',', '.'),
                errors='coerce'
            ).fillna(vIRPF)
            df.loc[df['IRPF'] > 1, 'IRPF'] /= 100

        # L_HASTA
        df['L_HASTA'] = df['L_HASTA'].fillna('01/01/2000')

        # -----------------------------------------------------------------
        # Agrupación
        # -----------------------------------------------------------------
        grouped = df.groupby(['SPCODE', 'L_DESDE', 'L_HASTA'])
        agg_dict = {'BRUTO': 'sum', 'CALCULO': 'sum'}
        df_d = grouped.agg(agg_dict).reset_index().rename(columns={'BRUTO': 'BRUTO_TOTAL', 'CALCULO': 'CALCULO_TOTAL'})

        # Copiar primeras columnas del grupo
        for col in df.columns:
            if col not in df_d.columns and col not in ['BRUTO', 'CALCULO']:
                df_d[col] = grouped[col].first().values

        # -----------------------------------------------------------------
        # Fechas y emisión
        # -----------------------------------------------------------------
        df_d['L_HASTA'] = pd.to_datetime(df_d['L_HASTA'], format='%d/%m/%Y', errors='coerce')
        df_d['MES'] = df_d['L_HASTA'].dt.month.fillna(1).astype(int)
        df_d['ANNO'] = df_d['L_HASTA'].dt.year.fillna(2000).astype(int)

        def calc_emision(mes: int, anno: int) -> str:
            mes += 1
            if mes > 12:
                mes = 1
                anno += 1
            return f"{DD_FEMISION:02d}/{mes:02d}/{anno}"

        df_d['EMISION'] = df_d.apply(lambda r: calc_emision(r['MES'], r['ANNO']), axis=1)
        df_d['MES'] = pd.to_datetime(df_d['EMISION'], format='%d/%m/%Y').dt.month
        df_d['ANNO'] = pd.to_datetime(df_d['EMISION'], format='%d/%m/%Y').dt.year

        # -----------------------------------------------------------------
        # Cálculos financieros
        # -----------------------------------------------------------------
        df_d['BASE_FACTURA'] = df_d['CALCULO_TOTAL'] - df_d['GASTOS'].clip(lower=0)
        df_d['CUOTA_IRPF'] = (df_d['BASE_FACTURA'] * df_d['IRPF']).round(2)
        df_d['TOTAL_FACTURA'] = (df_d['BASE_FACTURA'] - df_d['CUOTA_IRPF']).round(2)

        # -----------------------------------------------------------------
        # Generar FACTURA única
        # -----------------------------------------------------------------
        df_d['FACTURA'] = (
            df_d['SPCODE'].astype(str) + '-' +
            df_d['SOCIEDAD'].astype(str) + '-' +
            df_d['MES'].astype(str).str.zfill(2) + '-' +
            df_d['ANNO'].astype(str) + '-' +
            df_d.index.astype(str)
        )

        # -----------------------------------------------------------------
        # Formateo final
        # -----------------------------------------------------------------
        columns_order = [
            'FACTURA', 'MES', 'ANNO', 'EMISION', 'L_DESDE', 'L_HASTA', 'SPCODE', 'DOCTOR',
            'I_APELLIDO', 'II_APELLIDO', 'NOMBRE', 'DNI', 'ESPECIALIDAD', 'COLABORADOR',
            'COLEGIADO', 'CODIGO', 'DIRECCION', 'CIUDAD', 'POSTAL', 'TELEFONO', 'CUENTA',
            'ESTADO', 'EMAIL', 'CIF', 'SOCIEDAD', 'DESCRIPCION_SOC', 'DIRECCION_SOC',
            'POSTAL_SOC', 'PROVINCIA_SOC', 'REPRESENTANTE', 'NIF_REP', 'LIQUIDACION',
            'HHRR', 'BRUTO_TOTAL', 'CALCULO_TOTAL', 'GASTOS', 'BASE_FACTURA',
            'IRPF', 'CUOTA_IRPF', 'TOTAL_FACTURA'
        ]
        for col in columns_order:
            if col not in df_d.columns:
                df_d[col] = None

        df_d['L_HASTA'] = df_d['L_HASTA'].dt.strftime('%d/%m/%Y')
        for col in ['BRUTO_TOTAL', 'CALCULO_TOTAL', 'GASTOS', 'BASE_FACTURA', 'CUOTA_IRPF', 'TOTAL_FACTURA']:
            df_d[col] = df_d[col].apply(vu.format_currency)
        df_d['IRPF'] = df_d['IRPF'].apply(vu.format_percentage)

        df_d = df_d[columns_order]

        # -----------------------------------------------------------------
        # Guardar en DB
        # -----------------------------------------------------------------
        success = vu.df2tDB(df_d, sqlite3_dbpath, 'FACTURA', 'dentfact_factura_d')
        if not success:
            logger.error("Fallo al guardar df_factura_d")
            return None

        logger.info("get_factura_d completado con éxito.")
        return df_d

    except Exception as e:
        logger.exception(f"Error en get_factura_d: {e}")
        return None  # ← Nunca bloquea VeriFactu


# ---------------------------------------------------------------------
# 2. init_factura (MODIFICADO PARA FALLBACK)
# ---------------------------------------------------------------------
def init_factura() -> Dict[str, Any]:
    logger.info("Iniciando init_factura")
    try:
        df_importes_in = get_importes(tablas_dir, sqlite3_dbpath)
        if df_importes_in is not None and not df_importes_in.empty:
            logger.info("df_importes_in poblado con %d filas.", len(df_importes_in))
        else:
            logger.warning("get_importes devolvió DataFrame vacío. Se usará df_importes de la base de datos.")

        try:
            df_doctor, df_docpercent, df_centro, df_especialidad, df_sociedad = vu.getTables(df_importes_in)
        except (ValueError, sqlite3.Error) as e:
            logger.warning(f"Error en getTables: {e}")
            df_doctor = pd.DataFrame()
            df_docpercent = pd.DataFrame()
            df_centro = pd.DataFrame()
            df_especialidad = pd.DataFrame(columns=['ESPECIALIDAD', 'DESCRIPCION'])
            df_sociedad = pd.DataFrame()

        df_doctor = vu.dftDoctor(df_doctor, vGP=vGP, vGASTOS=vGASTOS)

        try:
            result = vu.updTables(
                df_doctor, 
                df_docpercent,
                df_centro, 
                df_especialidad, 
                df_sociedad, 
                db_path=sqlite3_dbpath,
                vIRPF=vIRPF
            )
            if not isinstance(result, dict):
                raise ValueError("El resultado de updTables no es un diccionario válido.")
            for tabla, datos in result.items():
                if not all(key in datos for key in ['inserted', 'skipped', 'errors']):
                    raise ValueError(f"Estructura inválida para la tabla {tabla} en el resultado.")
            logger.info("Ejecución de updTables finalizada correctamente: %s", result)
        except ValueError as ve:
            logger.error(f"Error de validación: {ve}")
            return {"success": False, "dataframes": {}, "message": f"Error de validación: {ve}"}
        except sqlite3.Error as se:
            logger.error(f"Error de SQLite: {se}")
            return {"success": False, "dataframes": {}, "message": f"Error de SQLite: {se}"}
        except Exception as e:
            logger.error(f"Error inesperado en updTables: {e}")
            return {"success": False, "dataframes": {}, "message": f"Error inesperado: {e}"}

        dataframes = loadALL(sqlite3_dbpath)
        df_importes_out = dataframes.get("df_importes", pd.DataFrame())
        df_centro = dataframes.get("df_centro", pd.DataFrame())
        df_especialidad = dataframes.get("df_especialidad", pd.DataFrame(columns=['ESPECIALIDAD', 'DESCRIPCION']))
        df_doctor = dataframes.get("df_doctor", pd.DataFrame())
        df_docpercent = dataframes.get("df_docpercent", pd.DataFrame())
        df_sociedad = dataframes.get("df_sociedad", pd.DataFrame())

        df_importes_out.to_csv(vPath / "df_importes.csv", index=False)

        ri = ['SPCODE', 'DOCTOR', 'ESPECIALIDAD', 'COLABORADOR', 'COLEGIADO',
              'CENTRO', 'N_CENTRO', 'CIF', 'LIQUIDACION', 'L_DESDE', 'L_HASTA',
              'HHRR', 'BRUTO', 'NETO', 'FECHA']
        
        df_importes_ri = df_importes_out[ri].copy()
        logger.info("Número de filas df_importes_ri: %d", len(df_importes_ri))
        df_importes_ri.to_csv(vPath / "df_importes_ri.csv", index=False)

        df_merge_pi = merge_pi(df_importes_ri, df_docpercent)
        valid_pi = len(df_importes_ri) == len(df_merge_pi)
        if valid_pi:
            logger.info("✅ Merge (merge_pi) completado correctamente.")
        else:
            logger.warning("⚠️ Inconsistencia en número de filas tras el merge (merge_pi).")
        logger.info("Número de filas merge_pi: %d", len(df_merge_pi))
        logger.info("Número de columnas merge_pi: %d", len(df_merge_pi.columns))
        logger.info("Columnas con valores nulos en merge_pi:\n%s", df_merge_pi.isnull().sum())
        df_merge_pi.to_csv(vPath / "df_merge_pi.csv", index=False)

        df_merge_do = merge_do(df_merge_pi, df_doctor)
        valid_do = len(df_merge_pi) == len(df_merge_do)
        if valid_do:
            logger.info("✅ Merge (merge_do) completado correctamente.")
        else:
            logger.warning("⚠️ Inconsistencia en número de filas tras el merge (merge_do).")
        logger.info("Número de filas merge_do: %d", len(df_merge_do))
        logger.info("Número de columnas merge_do: %d", len(df_merge_do.columns))
        logger.info("Columnas con valores nulos en merge_do:\n%s", df_merge_do.isnull().sum())
        df_merge_do.to_csv(vPath / "df_merge_do.csv", index=False)

        df_merge_so = merge_so(df_merge_do, df_sociedad)
        valid_so = len(df_merge_do) == len(df_merge_so)
        if valid_so:
            logger.info("✅ Merge (merge_so) completado correctamente.")
        else:
            logger.warning("⚠️ Inconsistencia en número de filas tras el merge (merge_so).")
        logger.info("Número de filas merge_so: %d", len(df_merge_so))
        logger.info("Número de columnas merge_so: %d", len(df_merge_so.columns))
        logger.info("Columnas con valores nulos en merge_so:\n%s", df_merge_so.isnull().sum())
        df_merge_so.to_csv(vPath / "df_merge_so.csv", index=False)

        # Validar df_factura_c_in
        df_factura_c_in = df_merge_so.copy()
        #df_factura_c_in.to_csv(vPath / "df_factura_c.csv", index=False)  # Guardar antes de procesar
        
        
        if not isinstance(df_factura_c_in, pd.DataFrame):
            logger.error(f"df_factura_c_in no es un DataFrame de pandas, tipo recibido: {type(df_factura_c_in)}")
            raise ValueError("df_factura_c_in debe ser un DataFrame de pandas")
        if df_factura_c_in.empty:
            logger.error("df_factura_c_in está vacío")
            raise ValueError("df_factura_c_in no puede estar vacío")
        logger.info(f"Columnas en df_factura_c_in: {list(df_factura_c_in.columns)}")
        logger.info(f"Filas en df_factura_c_in: {len(df_factura_c_in)}")
        
        df_factura_c_in.to_csv(vPath / "df_factura_c_in.csv", index=False)
        
        result = get_factura_c(sqlite3_dbpath, 'dentfact_factura_c', 'FACTURA', df_factura_c_in)
        if not result.empty:
            df_factura_c = result
        else:
            df_factura_c = vu.table2df(sqlite3_dbpath, 'dentfact_factura_c')

        df_factura_c.to_csv(vPath / "df_factura_c.csv", index=False, encoding='utf-8')

        # -------------------------------------------------------------
        # INTENTO DE GENERAR FACTURA_D
        # -------------------------------------------------------------
        df_factura_d = get_factura_d(df_factura_c)

        # -------------------------------------------------------------
        # VERIFACTU: SIEMPRE SE EJECUTA (con o sin df_factura_d)
        # -------------------------------------------------------------
        if df_factura_d is not None and not df_factura_d.empty:
            logger.info("Usando df_factura_d para VeriFactu")
            vv.init_verifactu()  # Usa Factura_D
        else:
            logger.warning("df_factura_d no disponible. Usando df_factura_c como fallback.")
            # Opción 1: Llamar función específica
            if hasattr(vv, 'init_verifactu_from_c'):
                vv.init_verifactu_from_c(df_factura_c)
            else:
                # Opción 2: Forzar con Factura_C → crea Factura_D temporalmente
                temp_d = df_factura_c.copy()
                temp_d['FACTURA'] = temp_d['FACTURA'].fillna('TEMP-' + pd.Series(range(len(temp_d))).astype(str))
                temp_d['MES'] = pd.to_datetime(temp_d['L_HASTA'], format='%d/%m/%Y', errors='coerce').dt.month
                temp_d['ANNO'] = pd.to_datetime(temp_d['L_HASTA'], format='%d/%m/%Y', errors='coerce').dt.year
                temp_d['EMISION'] = temp_d.apply(lambda r: f"21/{(r['MES'] % 12) + 1:02d}/{r['ANNO'] + (r['MES'] == 12)}", axis=1)
                temp_d['TOTAL_FACTURA'] = temp_d.get('NETO', 0)
                # Guardar temporalmente
                vu.df2tDB(temp_d, sqlite3_dbpath, 'FACTURA', 'dentfact_factura_d', overwrite=True)
                vv.init_verifactu()

        # Recargar para retorno
        df_factura_d = vu.table2df(sqlite3_dbpath, 'dentfact_factura_d')
        df_factura_d.to_csv(vPath / "df_factura_d.csv", index=False, encoding='utf-8')

        dataframes.update({
            "df_factura_c": df_factura_c,
            "df_factura_d": df_factura_d
        })

        return {
            "success": True,
            "dataframes": dataframes,
            "message": f"Procesado. C: {len(df_factura_c)}, D: {len(df_factura_d)}"
        }

    except Exception as e:
        logger.error(f"Error en init_factura: {e}", exc_info=True)
        return {"success": False, "dataframes": {}, "message": str(e)}
        
###########################################################################################################
      
# EJECUCIÓN PRINCIPAL
