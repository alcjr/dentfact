# views_utils.py
import logging
import sys
import pandas as pd
import sqlite3
import unicodedata
import hashlib
import locale
import os
from pathlib import Path
from configparser import ConfigParser
from typing import Dict, Optional
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Tuple, Optional, Dict, Any, List 
import sqlite3
import pandas as pd
import logging
import re
import os
import numpy as np
import traceback
from django.db import transaction
from io import BytesIO
from datetime import datetime
from decimal import Decimal, InvalidOperation
from datetime import datetime
from configparser import ConfigParser
from pathlib import Path

from django.http import HttpResponse, JsonResponse, HttpRequest 
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.db import connection, transaction, IntegrityError  # Añade IntegrityError aquí
from django.http import HttpResponse, JsonResponse, HttpRequest
from django.utils import timezone
# Resto de las importaciones...
from django.http import HttpResponse, JsonResponse, HttpRequest
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.template import loader, TemplateDoesNotExist
from django.shortcuts import get_object_or_404, render, redirect, render
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils.encoding import force_str
from django.core.exceptions import ValidationError

from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import action  # Añadir esta importación


from .models import (
    Importes, Factura_R, Factura_C, Factura_D,
    Doctor, Docpercent, Centro, Sociedad, Especialidad, Factura_V
)

from .serializers import (
    DoctorSerializer, DocpercentSerializer, CentroSerializer,
    EmpresaSerializer, EspecialidadSerializer, ImportesSerializer,
    Factura_RSerializer, Factura_CSerializer, Factura_DSerializer, Factura_VSerializer 
)


# ------------------------------------------------------------------------------
# CONFIGURACIÓN INICIAL
# ------------------------------------------------------------------------------
locale.setlocale(locale.LC_ALL, 'es_ES.UTF-8')
logger = logging.getLogger(__name__)

CONFIG_PATH = Path('c:/dentfact/config.ini')
config = ConfigParser()

def _get_float(section: str, option: str, fallback: float) -> float:
        try:
            return config.getfloat(section, option, fallback=fallback)
        except Exception:
            logger.warning(f"No se pudo leer {option} en sección {section}. Usando fallback: {fallback}")
            return float(fallback)

def _load_config(path: Path) -> ConfigParser:
    cp = ConfigParser()
    if not path.exists():
        logger.critical("No se encontró el archivo de configuración: %s", path)
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {path}")
    cp.read(path, encoding='utf-8')
    return cp

def _validate_path(path_str: str, name: str) -> Path:
    # Limpieza y normalización
    clean_str = str(path_str).strip().strip('"').strip("'")
    p = Path(os.path.normpath(clean_str))
    
    if not p.exists():
        logger.error("La ruta %s no existe: %s", name, repr(p))
        raise FileNotFoundError(f"La ruta {name} no existe: {p}")
    return p

try:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {CONFIG_PATH}")
    config.read(CONFIG_PATH, encoding='utf-8')

    def validate_path(path_str, name):
        path = Path(path_str)
        if not path.exists():
            logger.error(f"La ruta {name} no existe: {path}")
            raise FileNotFoundError(f"La ruta {name} no existe: {path}")
        return path

    pdf = validate_path(config.get('inputs', 'pdf'), 'pdf')
    tablas = validate_path(config.get('inputs', 'tablas'), 'tablas')
    logs = validate_path(config.get('outputs', 'logs'), 'logs')
    sqlite3_dbpath = validate_path(config.get('outputs', 'sqlite3_dbpath'), 'sqlite3_dbpath')
    vIRPF = _get_float('default', 'IRPF_PERCENTAGE', 0.15)
    vGP = _get_float('default', 'GABINETE_PERCENTAGE', 0.115)
    vGASTOS = _get_float('default', 'GASTOS', 50)
    
except Exception as e:
    logger.critical(f"Error crítico al leer el archivo de configuración: {e}", exc_info=True)
    raise

# ------------------------------------------------------------------------------
# FUNCIONES DE UTILIDAD GENERAL
# ------------------------------------------------------------------------------
def clean_str(val):
    """Normaliza texto a NFC y evita errores de codificación."""
    try:
        normalized = unicodedata.normalize('NFC', str(val))
        return normalized.encode('utf-8', errors='ignore').decode('utf-8').strip()
    except Exception:
        return ""

# Función para generar SPCODE
def SPCode(name):
    # Aseguramos que 'name' sea una cadena de caracteres
    if not isinstance(name, str):
        name = str(name)  # Convertir cualquier tipo a cadena
    
    # Generar el hash y el SPCODE
    hash_obj = hashlib.sha256(name.encode('utf-8'))
    hash_hex = hash_obj.hexdigest()
    return 'SP' + hash_hex[:4]


# ------------------------------------------------------------------------------
# FUNCIONES DE SINCRONIZACIÓN CON SQLITE
# ------------------------------------------------------------------------------

def df2tDB(pathDB: str, tableDB: str, keyTable: str, df_table: pd.DataFrame) -> bool:
    """
    Inserta el contenido de un DataFrame en una tabla SQLite con prevención robusta de duplicados.
    
    Args:
        pathDB (str): Ruta a la base de datos SQLite
        tableDB (str): Nombre de la tabla destino
        keyTable (str): Nombre de la clave primaria
        df_table (pd.DataFrame): DataFrame con datos a insertar

    Returns:
        bool: True si la carga es exitosa, False en caso de error
    """
    success = False
    conn = None
    
    try:
        logger.info(f"INICIANDO df2tDB: {len(df_table)} filas para tabla {tableDB}")
        
        if not isinstance(df_table, pd.DataFrame) or df_table.empty:
            logger.warning("DataFrame vacío o inválido")
            return False

        # Conexión
        conn = sqlite3.connect(pathDB)
        cursor = conn.cursor()

        # Sanitizar nombre de tabla
        tableDB = ''.join(c for c in tableDB if c.isalnum() or c == '_')

        # 1. VERIFICAR SI LA TABLA EXISTE
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tableDB,))
        table_exists = cursor.fetchone() is not None

        if not table_exists:
            # Crear tabla nueva
            column_defs = []
            for col in df_table.columns:
                if col == keyTable:
                    column_defs.append(f"{keyTable} INTEGER PRIMARY KEY AUTOINCREMENT")
                else:
                    col_type = 'REAL' if pd.api.types.is_numeric_dtype(df_table[col]) else 'TEXT'
                    column_defs.append(f"{col} {col_type}")
            
            create_stmt = f"CREATE TABLE {tableDB} ({', '.join(column_defs)})"
            cursor.execute(create_stmt)
            logger.info(f"Tabla {tableDB} creada con {len(df_table.columns)} columnas")
            
            # Insertar todos los datos (tabla nueva)
            placeholders = ', '.join(['?'] * len(df_table.columns))
            cols = ', '.join(df_table.columns)
            insert_sql = f"INSERT INTO {tableDB} ({cols}) VALUES ({placeholders})"
            
            # Preparar datos
            data_to_insert = []
            for _, row in df_table.iterrows():
                processed_row = []
                for val in row:
                    if pd.isna(val):
                        processed_row.append(None)
                    elif isinstance(val, (int, float)):
                        processed_row.append(float(val))
                    else:
                        processed_row.append(str(val))
                data_to_insert.append(tuple(processed_row))
            
            cursor.executemany(insert_sql, data_to_insert)
            conn.commit()
            
            inserted_count = cursor.rowcount
            logger.info(f"✅ {inserted_count} registros insertados en tabla nueva {tableDB}")
            success = True
            
        else:
            # 2. TABLA EXISTENTE - PREVENIR DUPLICADOS
            
            # Obtener conteo inicial
            cursor.execute(f"SELECT COUNT(*) FROM {tableDB}")
            count_before = cursor.fetchone()[0]
            logger.info(f"Registros existentes en {tableDB}: {count_before}")

            # Estrategia SEGURA: Eliminar todos los registros y reinsertar
            # (para evitar problemas complejos de detección de duplicados)
            cursor.execute(f"DELETE FROM {tableDB}")
            logger.info(f"Tabla {tableDB} limpiada para nueva inserción")

            # Insertar datos
            placeholders = ', '.join(['?'] * len(df_table.columns))
            cols = ', '.join(df_table.columns)
            insert_sql = f"INSERT INTO {tableDB} ({cols}) VALUES ({placeholders})"
            
            # Preparar datos
            data_to_insert = []
            for _, row in df_table.iterrows():
                processed_row = []
                for val in row:
                    if pd.isna(val):
                        processed_row.append(None)
                    elif isinstance(val, (int, float)):
                        processed_row.append(float(val))
                    else:
                        processed_row.append(str(val))
                data_to_insert.append(tuple(processed_row))
            
            cursor.executemany(insert_sql, data_to_insert)
            conn.commit()
            
            inserted_count = cursor.rowcount
            logger.info(f"✅ {inserted_count} registros insertados en tabla existente {tableDB}")

            # Verificación final
            cursor.execute(f"SELECT COUNT(*) FROM {tableDB}")
            count_after = cursor.fetchone()[0]
            
            if count_after == len(df_table):
                logger.info(f"✅ VALIDACIÓN EXITOSA: {count_after} registros en BD = {len(df_table)} filas de entrada")
                success = True
            else:
                logger.error(f"❌ VALIDACIÓN FALLIDA: {count_after} registros en BD vs {len(df_table)} esperados")
                success = False

    except Exception as e:
        logger.error(f"❌ ERROR en df2tDB: {str(e)}")
        if conn:
            conn.rollback()
        success = False

    finally:
        if conn:
            conn.close()
            logger.info("Conexión SQLite cerrada")

    return success

def dfi2tdb(df_importes, db_path=sqlite3_dbpath):
    """
    Inserta los datos de importes en la tabla dentfact_importes.
    Evita duplicados estrictos usando INSERT OR IGNORE.
    Corrige cálculo de filas no insertadas y valida datos.
    """
    conn = None
    required_columns = [
        "CENTRO", "N_CENTRO", "DOCTOR", "ESPECIALIDAD", "COLABORADOR",
        "COLEGIADO", "CIF", "LIQUIDACION", "L_DESDE", "L_HASTA", "PP_BASE",
        "PP_LIQUIDO", "PM_BASE", "PM_LIQUIDO", "P_BASE", "P_LIQUIDO",
        "R_BASE", "R_LIQUIDO", "C_FIJA", "C_TURNO", "PPA_BASE", "PPA_LIQUIDO",
        "PMA_BASE", "PMA_LIQUIDO", "PA_BASE", "PA_LIQUIDO", "HHRR", "BRUTO",
        "NETO", "SPCODE", "ANNO", "FECHA"
    ]

    column_types = {col: "TEXT" for col in required_columns}  # Todas las columnas son TEXT

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Verificar estructura de la tabla
        cursor.execute("PRAGMA table_info(dentfact_importes);")
        table_info = cursor.fetchall()
        logger.debug(f"Estructura de dentfact_importes: {table_info}")
        cursor.execute("PRAGMA index_list(dentfact_importes);")
        indexes = cursor.fetchall()
        logger.debug(f"Índices de dentfact_importes: {indexes}")

        # Recrear tabla para asegurar consistencia
        cursor.execute("DROP TABLE IF EXISTS dentfact_importes;")
        cols_def = ', '.join(f"{col} {column_types[col]}" for col in required_columns)
        cursor.execute(f"""
            CREATE TABLE dentfact_importes (
                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                {cols_def}
            );
        """)
        logger.info("Tabla dentfact_importes recreada.")

        # Añadir columnas faltantes y validar datos
        df_importes = df_importes.copy()
        for col in required_columns:
            if col not in df_importes.columns:
                df_importes[col] = ''
            df_importes[col] = df_importes[col].map(lambda x: clean_str(str(x)) if pd.notnull(x) else '')
            if df_importes[col].isna().any():
                logger.warning(f"Valores nulos en {col}:\n{df_importes[df_importes[col].isna()][['L_HASTA', 'SPCODE', 'CENTRO', 'ESPECIALIDAD', col]].to_string()}")

        df_importes = df_importes[required_columns]
        logger.debug(f"Muestra de df_importes tras validación:\n{df_importes.to_string()}")

        df_rows = len(df_importes)

        # Eliminar duplicados estrictos
        dups = df_importes[df_importes.duplicated(subset=required_columns, keep=False)]
        if not dups.empty:
            logger.warning(f"Se encontraron {len(dups)} filas duplicadas estrictas en df_importes:\n{dups.to_string()}")
            df_importes = df_importes.drop_duplicates(subset=required_columns, keep='first')
            logger.info(f"Duplicados eliminados. Nuevo tamaño: {len(df_importes)} filas")
        else:
            logger.info("No se encontraron duplicados estrictos en df_importes.")

        # Añadir índice temporal para rastrear filas
        df_importes['temp_index'] = range(len(df_importes))

        # Preparar inserción
        placeholders = ', '.join(['?'] * len(required_columns))
        insert_sql = f"""
            INSERT OR IGNORE INTO dentfact_importes ({', '.join(required_columns)})
            VALUES ({placeholders});
        """

        records = [tuple(r) for r in df_importes[required_columns].to_records(index=False)]
        logger.debug(f"Registros enviados a SQLite (primeras 5 filas):\n{records[:5]}")

        # Intentar inserción masiva
        cursor.executemany(insert_sql, records)
        conn.commit()

        # Obtener registros insertados
        cursor.execute(f"SELECT {', '.join(required_columns)} FROM dentfact_importes")
        inserted_records = cursor.fetchall()
        inserted_count = len(inserted_records)
        inserted_tuples = set(tuple(str(x) for x in r) for r in inserted_records)

        # Identificar filas no insertadas usando el índice temporal
        not_inserted_indices = df_importes[~df_importes.apply(lambda r: tuple(str(x) for x in r[required_columns]) in inserted_tuples, axis=1)]['temp_index']
        df_not_inserted = df_importes[df_importes['temp_index'].isin(not_inserted_indices)][required_columns]

        # Intentar inserción individual para filas no insertadas
        if not df_not_inserted.empty:
            logger.warning(f"Filas no insertadas tras executemany: {len(df_not_inserted)}\n{df_not_inserted.to_string()}")
            for _, row in df_not_inserted.iterrows():
                try:
                    cursor.execute(insert_sql, tuple(row[required_columns]))
                    conn.commit()
                    logger.debug(f"Inserción individual exitosa para fila: {row[['L_HASTA', 'SPCODE', 'CENTRO', 'ESPECIALIDAD']].to_dict()}")
                    inserted_count += 1
                    df_not_inserted = df_not_inserted.drop(row.name)
                except sqlite3.Error as e:
                    logger.error(f"Error al insertar fila individual {row[['L_HASTA', 'SPCODE', 'CENTRO', 'ESPECIALIDAD']].to_dict()}: {e}")

        # Calcular filas omitidas
        skipped_count = df_rows - inserted_count - len(df_not_inserted)

        logger.info(f"Filas DataFrame entrada: {df_rows}")
        logger.info(f"Registros insertados: {inserted_count}")
        logger.info(f"Registros omitidos (ya existían): {skipped_count}")
        if not df_not_inserted.empty:
            logger.warning(f"Registros no insertados: {len(df_not_inserted)}\n{df_not_inserted.to_string()}")

        # Limpiar índice temporal
        df_importes = df_importes.drop(columns=['temp_index'])

        return {
            "df_rows": df_rows,
            "inserted": inserted_count,
            "skipped": skipped_count,
            "not_inserted": df_not_inserted
        }

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error en dfi2tdb: {e}", exc_info=True)
        return {
            "df_rows": len(df_importes),
            "inserted": 0,
            "skipped": 0,
            "not_inserted": df_importes
        }

    finally:
        if conn:
            conn.close()

def clean_str(s):
    if not isinstance(s, str):
        return str(s) if s is not None else ''
    return s.strip()  # Solo elimina espacios al inicio y final

def df2tDB(df, db_path: str, pk_field: str, table_name: str) -> dict:
    """
    Guarda un DataFrame en una tabla SQLite, validando tipos, columnas y duplicados.

    Args:
        df (pd.DataFrame): DataFrame a guardar.
        db_path (str): Ruta completa a la base de datos SQLite.
        pk_field (str): Campo de clave primaria.
        table_name (str): Nombre de la tabla destino.

    Returns:
        dict: {'inserted': int, 'skipped': int}
    """
    import sqlite3
    import pandas as pd
    import logging

    logger = logging.getLogger(__name__)

    # 🔍 Validar tipo antes de cualquier operación
    if not isinstance(df, pd.DataFrame):
        logger.error(f"df_table no es un DataFrame de pandas, tipo recibido: {type(df)}")
        return {'inserted': 0, 'skipped': 0}

    logger.info(f"INICIANDO df2tDB: {len(df)} filas para tabla {db_path}::{table_name}")

    if df.empty:
        logger.warning("El DataFrame está vacío, no se insertarán datos.")
        return {'inserted': 0, 'skipped': 0}

    try:
        df = df.copy(deep=True)

        # 1️⃣ Obtener columnas reales de la tabla
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            db_columns = [col[1] for col in cursor.fetchall()]
            logger.info(f"Columnas en la tabla {table_name}: {db_columns}")

        valid_columns = [col for col in df.columns if col in db_columns]
        invalid_columns = [col for col in df.columns if col not in db_columns]

        if invalid_columns:
            logger.warning(f"Las siguientes columnas no existen en {table_name} y se eliminarán: {invalid_columns}")
            df = df[valid_columns]

        # 2️⃣ Convertir tipos correctamente
        numeric_columns = [
            'BRUTO', 'NETO', 'PORCENTAJE', 'IRPF', 'GASTOS',
            'HHRR', 'GABINETE_01', 'GABINETE_02', 'CALCULO'
        ]
        '''
        for col in df.columns:
            if col in numeric_columns:
                df.loc[:, col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
            else:
                # df.loc[:, col] = df[col].astype(str).fillna("")
                  df.loc[:, col] = df[col].astype(object).astype(str).fillna("")
        '''
        
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                df.loc[:, col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
            else:
                # Forzar tipo object ANTES de convertir a string (para evitar FutureWarning)
                df[col] = df[col].astype('object')
                df.loc[:, col] = df[col].astype(str).fillna("")




        # 3️⃣ Eliminar duplicados internos
        if pk_field in df.columns:
            dup_count = df[pk_field].duplicated().sum()
            if dup_count > 0:
                logger.warning(f"Se eliminarán {dup_count} duplicados internos basados en {pk_field}.")
                df = df.drop_duplicates(subset=[pk_field], keep='first')

        # 4️⃣ Eliminar registros ya existentes en la tabla SQLite
        with sqlite3.connect(db_path) as conn:
            if pk_field in df.columns:
                existing_pks = pd.read_sql_query(f"SELECT {pk_field} FROM {table_name}", conn)
                existing_pks = existing_pks[pk_field].astype(str).tolist()
                before = len(df)
                df = df[~df[pk_field].astype(str).isin(existing_pks)]
                skipped = before - len(df)
                logger.info(f"Registros existentes detectados: {skipped}")
            else:
                skipped = 0

        # 5️⃣ Insertar los registros restantes
        if df.empty:
            logger.info("No hay filas nuevas para insertar (todas existen en la BD).")
            return {'inserted': 0, 'skipped': skipped}

        with sqlite3.connect(db_path) as conn:
            inserted = df.to_sql(table_name, conn, if_exists='append', index=False)
            logger.info(f"Filas insertadas correctamente: {inserted}")

        return {'inserted': inserted, 'skipped': skipped}

    except sqlite3.Error as se:
        logger.error(f"Error de base de datos en df2tDB: {se}", exc_info=True)
        return {'inserted': 0, 'skipped': 0}

    except Exception as e:
        logger.error(f"Error inesperado en df2tDB: {e}", exc_info=True)
        return {'inserted': 0, 'skipped': 0}

# ------------------------------------------------------------------------------
# FUNCIONES DE EXCEL Y TABLAS
# ------------------------------------------------------------------------------
def xlsx2df(folder_path):
    """Convierte todos los archivos Excel en DataFrame único (recursivo)."""
    if not os.path.exists(folder_path):
        logger.error(f"Directorio no existe: {folder_path}")
        return pd.DataFrame()
    xlsx_files = [
        os.path.join(root, file)
        for root, _, files in os.walk(folder_path)
        for file in files if file.endswith('.xlsx') and not file.startswith('~$')
    ]
    if not xlsx_files:
        logger.warning(f"No se encontraron archivos .xlsx en {folder_path}")
        return pd.DataFrame()

    dfs = []
    for f in xlsx_files:
        try:
            dfs.append(pd.read_excel(f))
            logger.info(f"Leído {f}")
        except Exception as e:
            logger.error(f"Error leyendo {f}: {e}")

    if not dfs:
        return pd.DataFrame()

    df = pd.concat(dfs, ignore_index=True).drop_duplicates()
    logger.info(f"Archivos combinados: {len(df)} filas totales.")
    return df

def xlxs2df(folder_path):
    """Alias para mantener compatibilidad con llamadas antiguas."""
    return xlsx2df(folder_path)

def table2df(db_path, tabla_nombre):
    """Carga una tabla SQLite completa como DataFrame."""
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query(f"SELECT * FROM {tabla_nombre}", conn)
        conn.close()
        return df
    except Exception as e:
        logger.error(f"Error al cargar la tabla {tabla_nombre}: {e}")
        return pd.DataFrame()
    

def addSPCODE(df):
    """Agrega columna SPCODE basada en 'DOCTOR'."""
    if 'DOCTOR' not in df.columns:
        logger.warning("No se encontró columna 'DOCTOR'. No se agregó SPCODE.")
        df['SPCODE'] = ""
        return df
    df['SPCODE'] = df['DOCTOR'].apply(SPCode)
    return df

def renCol(df):
    """Renombra las columnas de los reportes Excel a nombres estándar."""
    column_mapping = {
        'Centro de Coste': 'CENTRO',
        'Nombre del Centro': 'N_CENTRO',
        'Nombre del Doctor': 'DOCTOR',
        'Especialidad': 'ESPECIALIDAD',
        'Código del Colaborador': 'COLABORADOR',
        'Número de Colegiado': 'COLEGIADO',
        'Colaborador CIF': 'CIF',
        'Estado Liquidación': 'LIQUIDACION',
        'Fecha de liquidación desde': 'L_DESDE',
        'Fecha liquidación hasta': 'L_HASTA',
        'Producción Privados Base': 'PP_BASE',
        'Producción Privados Liquido': 'PP_LIQUIDO',
        'Producción Mutua Base': 'PM_BASE',
        'Producción Mutua Liquido': 'PM_LIQUIDO',
        'Protésicos Base': 'P_BASE',
        'Protésicos Liquido': 'P_LIQUIDO',
        'Regularización Base': 'R_BASE',
        'Regularización Líquido': 'R_LIQUIDO',
        'Compensación Fija': 'C_FIJA',
        'Compensación Turno': 'C_TURNO',
        'Producción Privada Ant Base': 'PPA_BASE',
        'Producción Privada Ant Líquido': 'PPA_LIQUIDO',
        'Producción Mutua Ant Base': 'PMA_BASE',
        'Producción Mutua Ant Líquido': 'PMA_LIQUIDO',
        'Protésicos Anteriores Base': 'PA_BASE',
        'Protésicos Anteriores Líquido': 'PA_LIQUIDO',
        '% HHRR': 'HHRR',
        'Total a Cobrar Bruto': 'BRUTO',
        'Total a Cobrar Neto': 'NETO'
    }

    # Estandarizar nombres de columnas en el DataFrame
    df.columns = df.columns.str.strip().str.title()

    # Crear mapeo flexible ignorando mayúsculas, espacios y acentos
    def normalize_str(s):
        s = ''.join(c for c in unicodedata.normalize('NFD', str(s))
                    if unicodedata.category(c) != 'Mn')
        return s.lower().replace(' ', '')

    # Mapear columnas existentes
    available_cols = {normalize_str(col): col for col in df.columns}
    mapping = {}
    for src, dst in column_mapping.items():
        norm_src = normalize_str(src)
        if norm_src in available_cols:
            mapping[available_cols[norm_src]] = dst

    # Renombrar columnas encontradas
    df = df.rename(columns=mapping)

    # Añadir columnas no encontradas con None
    missing = [dst for src, dst in column_mapping.items() if dst not in df.columns]
    if missing:
        logger.warning(f"Columnas no encontradas en el Excel y añadidas con None: {', '.join(missing)}")
        for col in missing:
            df[col] = None

    logger.info(f"Columnas renombradas: {list(df.columns)}")
    return df

def get_table_info(db_path, table_name):
    logger.debug(f"Iniciando get_table_info con db_path={db_path}, table_name={table_name}")
    
    # Validar entrada
    if not os.path.exists(db_path):
        logger.error(f"El archivo de base de datos no existe: {db_path}")
        raise FileNotFoundError(f"El archivo de base de datos no existe: {db_path}")
    
    try:
        # Conectar a la base de datos
        logger.debug(f"Conectando a {db_path}")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Verificar si la tabla existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        if not cursor.fetchone():
            logger.error(f"La tabla {table_name} no existe en {db_path}")
            raise sqlite3.OperationalError(f"La tabla {table_name} no existe")
        
        # Obtener el número de registros
        logger.debug(f"Contando registros en {table_name}")
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        row_count = cursor.fetchone()[0]
        
        # Obtener información de las columnas
        logger.debug(f"Obteniendo metadatos de columnas para {table_name}")
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        
        # Imprimir resultados
        logger.info(f"Información de la tabla '{table_name}':")
        logger.info(f"Número de registros: {row_count}")
        logger.info("Columnas:")
        for col in columns:
            logger.info(f"- Nombre: {col[1]}, Tipo: {col[2]}, Not Null: {col[3]}, Default: {col[4]}, PK: {col[5]}")
        
        # Retornar datos para uso programático
        return {
            "table_name": table_name,
            "row_count": row_count,
            "columns": [
                {"name": col[1], "type": col[2], "not_null": col[3], "default": col[4], "pk": col[5]}
                for col in columns
            ]
        }
    
    except sqlite3.Error as e:
        logger.error(f"Error al conectar o consultar la base de datos: {e}")
        raise
    except Exception as e:
        logger.error(f"Error inesperado: {e}", exc_info=True)
        raise
    finally:
        if 'conn' in locals():
            conn.close()
            logger.debug(f"Conexión a {db_path} cerrada")
            

def _clean_str(val):
    """Normaliza texto a NFC y evita errores de codificación."""
    try:
        normalized = unicodedata.normalize('NFC', str(val))
        return normalized.encode('utf-8', errors='ignore').decode('utf-8').strip()
    except Exception: 
        return 

def load_table_to_dataframe(pathDB: str, dbTable: str) -> pd.DataFrame:
    """
    Carga una tabla de una base de datos SQLite en un pandas DataFrame.

    Args:
        pathDB (str): Ruta completa al archivo de la base de datos SQLite (ej. 'c:\\data\\dentfact.sqlite3').
        dbTable (str): Nombre de la tabla a cargar (ej. 'dentfact_importes').

    Returns:
        pd.DataFrame: DataFrame con los datos de la tabla. Devuelve un DataFrame vacío en caso de error.

    Raises:
        FileNotFoundError: Si la ruta de la base de datos no existe.
        ValueError: Si los parámetros de entrada no son válidos.
    """
    try:
        # Validar parámetros de entrada
        if not isinstance(pathDB, str) or not pathDB.strip():
            logger.error("El parámetro pathDB debe ser una cadena no vacía.")
            raise ValueError("El parámetro pathDB debe ser una cadena no vacía.")
        if not isinstance(dbTable, str) or not dbTable.strip():
            logger.error("El parámetro dbTable debe ser una cadena no vacía.")
            raise ValueError("El parámetro dbTable debe ser una cadena no vacía.")

        # Validar existencia del archivo de la base de datos
        db_path = Path(pathDB)
        if not db_path.exists():
            logger.error(f"El archivo de base de datos no existe: {pathDB}")
            raise FileNotFoundError(f"El archivo de base de datos no existe: {pathDB}")

        # Conectar a la base de datos
        logger.info(f"Cargando tabla {dbTable} desde {pathDB}")
        conn = sqlite3.connect(db_path)

        # Verificar si la tabla existe
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (dbTable,))
        if not cursor.fetchone():
            logger.warning(f"La tabla {dbTable} no existe en {pathDB}")
            conn.close()
            return pd.DataFrame()

        # Cargar la tabla en un DataFrame
        query = f"SELECT * FROM {dbTable}"
        df = pd.read_sql_query(query, conn)
        conn.close()

        # Registrar información sobre el DataFrame cargado
        if df.empty:
            logger.warning(f"La tabla {dbTable} está vacía.")
        else:
            logger.info(f"Tabla {dbTable} cargada correctamente con {len(df)} filas y {len(df.columns)} columnas.")
            logger.debug(f"Columnas del DataFrame: {list(df.columns)}")

        return df

    except FileNotFoundError as e:
        logger.error(f"Error al acceder a la base de datos: {e}")
        return pd.DataFrame()
    except sqlite3.Error as e:
        logger.error(f"Error de SQLite al cargar la tabla {dbTable}: {e}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Error inesperado al cargar la tabla {dbTable}: {e}", exc_info=True)
        return pd.DataFrame()
    

def convert_to_decimal(value):
    """
    Convierte un valor a decimal de forma robusta, manejando varios formatos.
    """
    if pd.isna(value) or value is None or value == '':
        return None
    
    try:
        # Convertir a string y limpiar
        str_value = str(value).strip()
        
        # Reemplazar comas por puntos para formato europeo
        str_value = str_value.replace(',', '.')
        
        # Eliminar espacios y caracteres no numéricos (excepto punto y signo)
        cleaned = ''.join(c for c in str_value if c.isdigit() or c in '.-')
        
        if not cleaned or cleaned == '-' or cleaned == '.':
            return None
            
        # Convertir a Decimal
        decimal_value = Decimal(cleaned)
        
        # Redondear a 2 decimales como espera el modelo
        return round(decimal_value, 2)
        
    except (InvalidOperation, ValueError, TypeError):
        logger.debug("No se pudo convertir a decimal: %s", value)
        return None

def clean_text_field(series):
    """
    Limpia un campo de texto según las especificaciones del modelo.
    """
    return (series
            .astype(str)
            .replace(['nan', 'None', 'NULL', 'N/A', 'null'], '', regex=True)
            .str.strip()
            .fillna(''))

def ensure_data_types(df):
    """
    Asegura que los tipos de datos en el DataFrame final coincidan con el modelo.
    """
    # Para campos decimales, convertir a string con formato adecuado
    decimal_columns = ['GASTOS', 'GABINETE_01', 'GABINETE_02']
    for col in decimal_columns:
        if col in df.columns:
            # Mantener como float para pandas, se convertirá al guardar en BD
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Para campos de texto, asegurar que son strings
    text_columns = [
        'COLEGIADO', 'DOCTOR', 'I_APELLIDO', 'II_APELLIDO', 'NOMBRE', 'DNI',
        'SOCIEDAD', 'ESTADO', 'EMAIL', 'DIRECCION', 'CIUDAD', 'POSTAL',
        'TELEFONO', 'CUENTA', 'CODIGO', 'ESPECIALIDAD', 'COLABORADOR'
    ]
    
    for col in text_columns:
        if col in df.columns:
            df[col] = df[col].fillna('').astype(str)
    
    return df

def log_merge_results(df_merge_do, df_doctor_subset, unique_doctor_columns):
    """
    Registra resultados detallados del merge para debugging.
    """
    # Filas no emparejadas
    if unique_doctor_columns:
        first_doctor_col = list(unique_doctor_columns)[0]
        unmatched = df_merge_do[df_merge_do[first_doctor_col].isna()]['SPCODE'].unique()
        if len(unmatched) > 0:
            logger.warning("SPCODE sin correspondencia en df_doctor: %s", unmatched[:5])
    
    # Estadísticas de columnas
    logger.info("Merge completado - Filas: %d, Columnas: %d", 
                len(df_merge_do), len(df_merge_do.columns))
    
    # Verificar valores específicos problemáticos
    sample_check_columns = ['GASTOS', 'GABINETE_01', 'GABINETE_02', 'I_APELLIDO', 'NOMBRE']
    for col in sample_check_columns:
        if col in df_merge_do.columns:
            non_null_count = df_merge_do[col].notna().sum()
            empty_count = (df_merge_do[col] == '').sum()
            logger.debug("Columna %s - No nulos: %d, Vacíos: %d", 
                        col, non_null_count, empty_count)

def _log_head(df: pd.DataFrame, n: int = 3) -> None:
    try:
        logger.debug("Muestra de filas:\n%s", df.head(n).to_string())
    except Exception:
        logger.debug("No se pudo mostrar la muestra del DataFrame.")

def _coerce_numeric_columns(df: pd.DataFrame, numeric_columns: list) -> Dict[str, pd.Index]:
    problem_indices = {}
    for col in numeric_columns:
        if col in df.columns:
            converted = pd.to_numeric(df[col], errors='coerce')
            problems = df.index[converted.isna() & df[col].notna()]
            if not problems.empty:
                problem_indices[col] = problems
                logger.warning("Columna %s: %d valores no numéricos detectados.", col, len(problems))
                logger.debug("Índices problemáticos en %s: %s", col, list(problems[:5]))
            df[col] = converted
    return problem_indices

def getTables(df_importes_in: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Crea tablas especializadas (doctores, porcentajes, centros, sociedades, especialidades) 
    a partir de un DataFrame de importes. 

    Args:
        df_importes_in (pd.DataFrame): DataFrame con datos de importes.

    Returns:
        Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]: 
        DataFrames para doctores, docpercent, centros, especialidades, sociedades.

    Raises:
        ValueError: Si el DataFrame de entrada está vacío o faltan columnas requeridas.
    """
    logger.info("Iniciando creación de tablas especializadas")

    # Validar DataFrame de entrada
    if df_importes_in is None or df_importes_in.empty:
        logger.error("DataFrame de importes vacío o None")
        raise ValueError("DataFrame de importes vacío o None")
    required_cols = ['SPCODE', 'DOCTOR', 'ESPECIALIDAD', 'COLABORADOR', 'COLEGIADO', 'CIF', 'CENTRO', 'N_CENTRO']
    missing_cols = [col for col in required_cols if col not in df_importes_in.columns]
    if missing_cols:
        logger.error(f"Faltan columnas en df_importes_in: {missing_cols}")
        raise ValueError(f"Faltan columnas en df_importes_in: {missing_cols}")
    logger.info(f"Dataframe de entrada validado. Filas: {len(df_importes_in)}, Columnas: {len(df_importes_in.columns)}")

    # Normalizar todas las columnas a mayúsculas para consistencia
    df_importes_in.columns = [col.upper() for col in df_importes_in.columns]
    logger.info("Columnas de df_importes_in normalizadas a mayúsculas")

    # Crear dataframe de doctores (únicos por SPCODE)
    logger.info("Creando dataframe de doctores")
    df_doctor = df_importes_in[['SPCODE', 'DOCTOR', 'ESPECIALIDAD', 'COLABORADOR', 'COLEGIADO', 'CIF']].drop_duplicates(subset=['SPCODE'])
    # Añadir columnas requeridas si faltan, con valores por defecto
    doctor_required = ['SPCODE', 'DOCTOR', 'ESPECIALIDAD', 'COLABORADOR', 'COLEGIADO', 'CIF', 
                       'I_APELLIDO', 'II_APELLIDO', 'NOMBRE', 'DNI', 'GASTOS', 'ESTADO', 
                       'EMAIL', 'DIRECCION', 'CIUDAD', 'POSTAL', 'TELEFONO', 'CUENTA', 
                       'GABINETE_01', 'GABINETE_02']
    for col in doctor_required:
        if col not in df_doctor.columns:
            df_doctor[col] = None  # o '' para strings
    df_doctor.columns = [col.upper() for col in df_doctor.columns]  # Asegurar mayúsculas
    logger.info(f"Dataframe df_doctor creado: {len(df_doctor)} registros")

    # Crear dataframe de porcentajes por doctor (únicos por SPCODE, ESPECIALIDAD, CENTRO)
    logger.info("Creando dataframe de porcentajes por doctor")
    df_docpercent = df_importes_in[['SPCODE', 'ESPECIALIDAD', 'CENTRO']].drop_duplicates()
    # Añadir columnas requeridas, usando SPCODE_id (minúsculas _id) para compatibilidad con updTables
    docpercent_required = ['SPCODE_id', 'ESPECIALIDAD', 'CENTRO', 'IRPF', 'PORCENTAJE']
    df_docpercent = df_docpercent.rename(columns={'SPCODE': 'SPCODE_id'})
    for col in docpercent_required:
        if col not in df_docpercent.columns:
            df_docpercent[col] = None
    df_docpercent.columns = [col.upper() if col != 'SPCODE_id' else col for col in df_docpercent.columns]
    logger.info(f"Dataframe df_docpercent creado: {len(df_docpercent)} registros")

    # Crear dataframe de centros (únicos por CENTRO)
    logger.info("Creando dataframe de centros")
    df_centro = df_importes_in[['CENTRO', 'N_CENTRO']].drop_duplicates(subset=['CENTRO'])
    # Añadir columnas requeridas
    centro_required = ['CENTRO', 'N_CENTRO', 'DIRECCION', 'POBLACION', 'PROVINCIA', 'POSTAL', 'EMAIL', 'WWW', 'DESCRIPCION']
    for col in centro_required:
        if col not in df_centro.columns:
            df_centro[col] = None
    df_centro.columns = [col.upper() for col in df_centro.columns]
    logger.info(f"Dataframe df_centro creado: {len(df_centro)} registros")

    # Crear dataframe de sociedades (únicos por CIF)
    logger.info("Creando dataframe de sociedades")
    df_sociedad = df_importes_in[['CIF']].drop_duplicates()
    # Añadir columnas requeridas
    sociedad_required = ['CIF', 'SOCIEDAD', 'DESCRIPCION_SOC', 'DIRECCION_SOC', 
                        'PROVINCIA_SOC', 'POSTAL_SOC', 'REPRESENTANTE', 'NIF_REP']
    df_sociedad['SOCIEDAD'] = df_importes_in['DOCTOR'].fillna('')  # Usar DOCTOR como proxy para SOCIEDAD
    for col in sociedad_required:
        if col not in df_sociedad.columns:
            df_sociedad[col] = None
    df_sociedad.columns = [col.upper() for col in df_sociedad.columns]
    logger.info(f"Dataframe df_sociedad creado: {len(df_sociedad)} registros")

    # Crear dataframe de especialidades (únicos por ESPECIALIDAD)
    logger.info("Creando dataframe de especialidades")
    df_especialidad = df_importes_in[['ESPECIALIDAD']].drop_duplicates()
    # Añadir DESCRIPCION si falta
    df_especialidad['DESCRIPCION'] = None
    df_especialidad.columns = [col.upper() for col in df_especialidad.columns]
    logger.info(f"Dataframe df_especialidad creado: {len(df_especialidad)} registros")

    # Logging final de tamaños y columnas
    logger.info(f"Dataframe df_doctor: {len(df_doctor)} registros, {len(df_doctor.columns)} columnas, Columnas: {list(df_doctor.columns)}")
    logger.info(f"Dataframe df_docpercent: {len(df_docpercent)} registros, {len(df_docpercent.columns)} columnas, Columnas: {list(df_docpercent.columns)}")
    logger.info(f"Dataframe df_centro: {len(df_centro)} registros, {len(df_centro.columns)} columnas, Columnas: {list(df_centro.columns)}")
    logger.info(f"Dataframe df_sociedad: {len(df_sociedad)} registros, {len(df_sociedad.columns)} columnas, Columnas: {list(df_sociedad.columns)}")
    logger.info(f"Dataframe df_especialidad: {len(df_especialidad)} registros, {len(df_especialidad.columns)} columnas, Columnas: {list(df_especialidad.columns)}")

    logger.info("Proceso de creación de tablas completado exitosamente")
    return df_doctor, df_docpercent, df_centro, df_especialidad, df_sociedad


def updTables(
    df_doctor:[pd.DataFrame],
    df_docpercent: [pd.DataFrame],
    df_centro: [pd.DataFrame],
    df_especialidad:[pd.DataFrame],
    df_sociedad:[pd.DataFrame],
    db_path: str = r"c:\data\dentfact.sqlite3",
    vIRPF: float = 0.15
) -> dict:
    """
    Inserta datos de DataFrames en las tablas correspondientes de la base de datos SQLite.

    Args:
        df_doctor, df_docpercent, df_centro, df_especialidad, df_sociedad: DataFrames opcionales.
        db_path: Ruta a la base de datos SQLite.
        vIRPF: Valor por defecto para la columna IRPF.

    Returns:
        dict: Conteo de registros insertados por tabla y errores.
    """
    logger = logging.getLogger(__name__)
    result = {
        'dentfact_doctor': {'inserted': 0, 'skipped': 0, 'errors': []},
        'dentfact_docpercent': {'inserted': 0, 'skipped': 0, 'errors': []},
        'dentfact_centro': {'inserted': 0, 'skipped': 0, 'errors': []},
        'dentfact_especialidad': {'inserted': 0, 'skipped': 0, 'errors': []},
        'dentfact_sociedad': {'inserted': 0, 'skipped': 0, 'errors': []}
    }
    required_columns = {
        'dentfact_doctor': ['SPCODE', 'DOCTOR', 'ESPECIALIDAD', 'COLABORADOR', 'COLEGIADO', 'CIF',
                            'I_APELLIDO', 'II_APELLIDO', 'NOMBRE', 'DNI', 'GASTOS', 'ESTADO',
                            'EMAIL', 'DIRECCION', 'CIUDAD', 'POSTAL', 'TELEFONO', 'CUENTA',
                            'GABINETE_01', 'GABINETE_02'],
        'dentfact_docpercent': ['SPCODE_id', 'CENTRO', 'ESPECIALIDAD', 'PORCENTAJE', 'IRPF'],
        'dentfact_centro': ['CENTRO', 'N_CENTRO', 'DIRECCION', 'POBLACION', 'PROVINCIA',
                            'POSTAL', 'EMAIL', 'WWW', 'DESCRIPCION'],
        'dentfact_especialidad': ['ESPECIALIDAD', 'DESCRIPCION'],
        'dentfact_sociedad': ['CIF', 'SOCIEDAD', 'DESCRIPCION_SOC', 'DIRECCION_SOC',
                              'PROVINCIA_SOC', 'POSTAL_SOC', 'REPRESENTANTE', 'NIF_REP']
    }
    dataframes = {
        'dentfact_doctor': df_doctor,
        'dentfact_docpercent': df_docpercent,
        'dentfact_centro': df_centro,
        'dentfact_especialidad': df_especialidad,
        'dentfact_sociedad': df_sociedad
    }

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            # Crear tablas si no existen
            for table_name in required_columns:
                columns = required_columns[table_name]
                col_defs = [f"{col} TEXT" for col in columns]
                if table_name == 'dentfact_doctor':
                    col_defs[columns.index('GASTOS')] = 'GASTOS REAL'
                    col_defs[columns.index('GABINETE_01')] = 'GABINETE_01 REAL'
                    col_defs[columns.index('GABINETE_02')] = 'GABINETE_02 REAL'
                elif table_name == 'dentfact_docpercent':
                    col_defs[columns.index('PORCENTAJE')] = 'PORCENTAJE REAL'
                    col_defs[columns.index('IRPF')] = 'IRPF REAL'
                primary_key = 'SPCODE' if table_name == 'dentfact_doctor' else \
                             'CENTRO' if table_name == 'dentfact_centro' else \
                             'ESPECIALIDAD' if table_name == 'dentfact_especialidad' else \
                             'CIF' if table_name == 'dentfact_sociedad' else \
                             'SPCODE_id, CENTRO, ESPECIALIDAD'
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        {', '.join(col_defs)},
                        PRIMARY KEY ({primary_key})
                    )
                """)
                logger.info(f"Tabla {table_name} verificada/creada.")

            for table_name, df in dataframes.items():
                if df is None or df.empty:
                    logger.info(f"No se proporcionó DataFrame válido para {table_name}. Saltando.")
                    result[table_name]['skipped'] += len(df) if df is not None else 0
                    continue
                logger.info(f"Procesando {table_name}. Filas a procesar: {len(df)}")
                # Añadir columnas faltantes con None
                for col in required_columns[table_name]:
                    if col not in df.columns:
                        df[col] = None
                        logger.warning(f"Columna {col} no encontrada en {table_name}. Añadida con None.")
                
                columns = required_columns[table_name]
                placeholders = ', '.join(['?' for _ in columns])
                sql = f"INSERT OR IGNORE INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
                primary_key = 'SPCODE' if table_name == 'dentfact_doctor' else \
                             ('SPCODE_id', 'CENTRO', 'ESPECIALIDAD') if table_name == 'dentfact_docpercent' else \
                             'CENTRO' if table_name == 'dentfact_centro' else \
                             'ESPECIALIDAD' if table_name == 'dentfact_especialidad' else \
                             'CIF'

                for _, row in df.iterrows():
                    try:
                        row = row.replace(['', 'nan', 'None'], np.nan).where(pd.notnull(row), None)
                        if table_name == 'dentfact_docpercent':
                            row['PORCENTAJE'] = row['PORCENTAJE'] if pd.notnull(row['PORCENTAJE']) else 0
                            row['IRPF'] = row['IRPF'] if pd.notnull(row['IRPF']) else vIRPF
                        if isinstance(primary_key, tuple):
                            conditions = ' AND '.join([f"{pk} = ?" for pk in primary_key])
                            values = tuple(row[pk] for pk in primary_key if pd.notnull(row[pk]))
                            if len(values) != len(primary_key):
                                logger.warning(f"Valores nulos en clave primaria {primary_key} para {table_name}. Saltando registro.")
                                result[table_name]['skipped'] += 1
                                continue
                        else:
                            conditions = f"{primary_key} = ?"
                            values = (row[primary_key],)
                            if pd.isna(row[primary_key]):
                                logger.warning(f"Valor nulo en clave primaria {primary_key} para {table_name}. Saltando registro.")
                                result[table_name]['skipped'] += 1
                                continue
                        cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {conditions}", values)
                        if cursor.fetchone()[0] > 0:
                            result[table_name]['skipped'] += 1
                            logger.debug(f"Registro duplicado en {table_name}: {values}. Saltando.")
                            continue
                        insert_values = tuple(row[col] for col in columns)
                        cursor.execute(sql, insert_values)
                        result[table_name]['inserted'] += 1
                        logger.debug(f"Insertado en {table_name}: {insert_values}")
                    except sqlite3.Error as e:
                        error_msg = f"Error al insertar en {table_name} para {values}: {str(e)}"
                        result[table_name]['errors'].append(error_msg)
                        logger.error(error_msg)
                logger.info(f"Completado {table_name}. Insertados: {result[table_name]['inserted']}, Saltados: {result[table_name]['skipped']}, Errores: {len(result[table_name]['errors'])}")
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error en la conexión a la base de datos: {str(e)}")
        raise
    return result

def dftDoctor(df_doctor: pd.DataFrame, vGP: float = 0.115, vGASTOS: float = 50.0) -> pd.DataFrame:
    required_cols = ['GABINETE_01', 'GABINETE_02', 'GASTOS']
    missing_cols = [col for col in required_cols if col not in df_doctor.columns]
    if missing_cols:
        raise ValueError(f"Faltan columnas en df_doctor: {missing_cols}")
    
    df_doctor = df_doctor.copy()
    
    for col in ['GABINETE_01', 'GABINETE_02']:
        df_doctor[col] = pd.to_numeric(df_doctor[col], errors='coerce').astype(float)
        mask_large = df_doctor[col] > 1
        if mask_large.any():
            logger.warning(f"Valores de {col} > 1 encontrados: {df_doctor.loc[mask_large, col].head().tolist()}")
            df_doctor.loc[mask_large, col] /= 100
            mask_still_large = df_doctor[col] > 1
            if mask_still_large.any():
                logger.warning(f"Valores de {col} > 1 tras división: {df_doctor.loc[mask_still_large, col].head().tolist()}. Capeando a 1.")
                df_doctor.loc[mask_still_large, col] = 1.0
        df_doctor[col] = df_doctor[col].fillna(vGP)
    
    df_doctor['GASTOS'] = pd.to_numeric(df_doctor['GASTOS'], errors='coerce').astype(float).fillna(vGASTOS)
    
    for col in required_cols:
        if not pd.api.types.is_numeric_dtype(df_doctor[col]):
            logger.error(f"La columna {col} no es numérica: {df_doctor[col].dtype}")
            raise ValueError(f"La columna {col} contiene valores no numéricos")
    
    logger.info(f"Procesamiento de df_doctor completado. Filas: {len(df_doctor)}")
    return df_doctor


def clean_duplicates(db_path: str, tables: List[Dict[str, any]] = None, keep: str = 'first') -> Dict[str, Dict[str, int]]:
    """
    Elimina registros duplicados en las tablas especificadas basándose en sus claves primarias o restricciones unique_together.
    Excluye las tablas dentfact_importes y dentfact_docpercent.
    Respeta dependencias entre tablas para evitar violaciones de claves foráneas.
    Registra todas las acciones en un archivo de log.

    Parámetros:
    -----------
    db_path : str
        Ruta completa a la base de datos SQLite (e.g., 'c:/dentfact.sqlite3').
    tables : List[Dict[str, any]], opcional
        Lista de diccionarios con la configuración de cada tabla:
        {'table': str, 'pk_cols': List[str], 'unique_cols': List[str] (opcional), 'order': int}
        Si no se proporciona, se usa una lista predeterminada excluyendo dentfact_importes y dentfact_docpercent.
    keep : str, opcional
        Criterio para conservar registros duplicados ('first' o 'last'). Por defecto, 'first'.

    Retorna:
    --------
    Dict[str, Dict[str, int]]
        Diccionario con métricas por tabla: {'table_name': {'duplicates_found': int, 'deleted': int, 'errors': int}}.

    Excepciones:
    ------------
    ValueError
        Si la ruta de la base de datos es inválida o keep no es 'first'/'last'.
    sqlite3.Error
        Si ocurre un error en la base de datos (e.g., violación de clave foránea).
    """
    if not Path(db_path).is_file():
        logger.error(f"Ruta de base de datos inválida: {db_path}")
        raise ValueError(f"Ruta de base de datos inválida: {db_path}")

    if keep not in ['first', 'last']:
        logger.error(f"Criterio 'keep' inválido: {keep}. Debe ser 'first' o 'last'.")
        raise ValueError(f"Criterio 'keep' inválido: {keep}")

    # Definir tablas a limpiar, excluyendo dentfact_importes y dentfact_docpercent
    default_tables = [
        {'table': 'dentfact_especialidad', 'pk_cols': ['ESPECIALIDAD'], 'order': 1},
        {'table': 'dentfact_centro', 'pk_cols': ['CENTRO'], 'order': 2},
        {'table': 'dentfact_sociedad', 'pk_cols': ['ID_SOC'], 'unique_cols': ['CIF'], 'order': 3},
        {'table': 'dentfact_doctor', 'pk_cols': ['SPCODE'], 'order': 4},
    ]
    tables = tables or default_tables
    tables.sort(key=lambda x: x['order'])  # Ordenar por dependencia

    results = {table['table']: {'duplicates_found': 0, 'deleted': 0, 'errors': 0} for table in tables}

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        logger.info(f"Conexión establecida con la base de datos: {db_path}")

        for table_config in tables:
            table = table_config['table']
            pk_cols = table_config['pk_cols']
            unique_cols = table_config.get('unique_cols', pk_cols)  # Usar unique_cols si está definido
            logger.info(f"Procesando tabla {table} con claves: {unique_cols}")

            # Identificar duplicados
            pk_cols_str = ', '.join(unique_cols)
            query_count = f"""
                SELECT {pk_cols_str}, COUNT(*) as count
                FROM {table}
                GROUP BY {pk_cols_str}
                HAVING count > 1
            """
            try:
                duplicates_df = pd.read_sql_query(query_count, conn)
                duplicates_count = len(duplicates_df)
                results[table]['duplicates_found'] = duplicates_count
                if duplicates_count == 0:
                    logger.info(f"No se encontraron duplicados en {table}.")
                    continue
                logger.warning(f"Se encontraron {duplicates_count} grupos de duplicados en {table}.")
                logger.debug(f"Duplicados:\n{duplicates_df.to_string()}")

                # Eliminar duplicados, conservar el primero o último según 'keep'
                rowid_selector = 'MIN(rowid)' if keep == 'first' else 'MAX(rowid)'
                delete_query = f"""
                    DELETE FROM {table}
                    WHERE rowid NOT IN (
                        SELECT {rowid_selector}
                        FROM {table}
                        GROUP BY {pk_cols_str}
                    )
                """
                try:
                    cursor.execute(delete_query)
                    deleted = cursor.rowcount
                    results[table]['deleted'] = deleted
                    logger.info(f"Eliminados {deleted} registros duplicados en {table}.")
                except sqlite3.Error as e:
                    results[table]['errors'] += 1
                    logger.error(f"Error al eliminar duplicados en {table}: {e}")
            except sqlite3.Error as e:
                results[table]['errors'] += 1
                logger.error(f"Error al identificar duplicados en {table}: {e}")

        conn.commit()
        logger.info("Cambios confirmados en la base de datos.")
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Error en la base de datos. Realizando rollback: {e}")
        raise
    finally:
        conn.close()
        logger.info("Conexión con la base de datos cerrada.")

    # Resumen de resultados
    logger.info("\nResumen de limpieza de duplicados:")
    for table, metrics in results.items():
        logger.info(f"  🗂️ {table}: Duplicados encontrados: {metrics['duplicates_found']}, "
                    f"Eliminados: {metrics['deleted']}, Errores: {metrics['errors']}")

    return results


def updTables(
    df_doctor: Optional[pd.DataFrame] = None,
    df_docpercent: Optional[pd.DataFrame] = None,
    df_centro: Optional[pd.DataFrame] = None,
    df_especialidad: Optional[pd.DataFrame] = None,
    df_sociedad: Optional[pd.DataFrame] = None,
    db_path: str = r"c:\data\dentfact.sqlite3",
    vIRPF: float = 0.15
) -> dict:
    """
    Inserta datos de DataFrames en las tablas correspondientes de la base de datos SQLite dentfact.sqlite3.

    Args:
        df_doctor (pd.DataFrame, optional): DataFrame con datos para la tabla dentfact_doctor.
        df_docpercent (pd.DataFrame, optional): DataFrame con datos para la tabla dentfact_docpercent.
        df_centro (pd.DataFrame, optional): DataFrame con datos para la tabla dentfact_centro.
        df_especialidad (pd.DataFrame, optional): DataFrame con datos para la tabla dentfact_especialidad.
        df_sociedad (pd.DataFrame, optional): DataFrame con datos para la tabla dentfact_sociedad.
        db_path (str): Ruta a la base de datos SQLite (por defecto: c://data//dentfact.sqlite3).
        vIRPF (float): Valor por defecto para la columna IRPF en dentfact_docpercent (por defecto: 0.15).

    Returns:
        dict: Diccionario con el conteo de registros insertados por tabla y cualquier error encontrado.

    Raises:
        ValueError: Si los DataFrames no contienen las columnas requeridas o están vacíos.
        sqlite3.Error: Si ocurre un error al interactuar con la base de datos.
    """
    logger = logging.getLogger(__name__)
    
    # Configurar logging si no está configurado
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

   
    # Resultado para rastrear inserciones y errores
    result = {
        'dentfact_doctor': {'inserted': 0, 'skipped': 0, 'errors': []},
        'dentfact_docpercent': {'inserted': 0, 'skipped': 0, 'errors': []},
        'dentfact_centro': {'inserted': 0, 'skipped': 0, 'errors': []},
        'dentfact_especialidad': {'inserted': 0, 'skipped': 0, 'errors': []},
        'dentfact_sociedad': {'inserted': 0, 'skipped': 0, 'errors': []}
    }

    # Definir columnas requeridas por tabla
    required_columns = {
        'dentfact_doctor': ['SPCODE', 'DOCTOR', 'ESPECIALIDAD', 'COLABORADOR', 'COLEGIADO', 'CIF',
                           'I_APELLIDO', 'II_APELLIDO', 'NOMBRE', 'DNI', 'GASTOS', 'ESTADO',
                           'EMAIL', 'DIRECCION', 'CIUDAD', 'POSTAL', 'TELEFONO', 'CUENTA',
                           'GABINETE_01', 'GABINETE_02'],
        'dentfact_docpercent': ['SPCODE_id', 'CENTRO', 'ESPECIALIDAD', 'PORCENTAJE', 'IRPF'],
        'dentfact_centro': ['CENTRO', 'N_CENTRO', 'DIRECCION', 'POBLACION', 'PROVINCIA',
                           'POSTAL', 'EMAIL', 'WWW', 'DESCRIPCION'],
        'dentfact_especialidad': ['ESPECIALIDAD', 'DESCRIPCION'],
        'dentfact_sociedad': ['CIF', 'SOCIEDAD', 'DESCRIPCION_SOC', 'DIRECCION_SOC',
                             'PROVINCIA_SOC', 'POSTAL_SOC', 'REPRESENTANTE', 'NIF_REP']
    }

    # Validar DataFrames de entrada
    dataframes = {
        'dentfact_doctor': df_doctor,
        'dentfact_docpercent': df_docpercent,
        'dentfact_centro': df_centro,
        'dentfact_especialidad': df_especialidad,
        'dentfact_sociedad': df_sociedad
    }

    for table_name, df in dataframes.items():
        if df is not None:
            if df.empty:
                logger.warning(f"El DataFrame para {table_name} está vacío. No se procesará.")
                continue
            missing_cols = [col for col in required_columns[table_name] if col not in df.columns]
            if missing_cols:
                error_msg = f"Faltan columnas en {table_name}: {missing_cols}"
                logger.error(error_msg)
                raise ValueError(error_msg)

    try:
        # Conectar a la base de datos
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Procesar cada tabla
            for table_name, df in dataframes.items():
                if df is None or df.empty:
                    logger.info(f"No se proporcionó DataFrame para {table_name}. Saltando.")
                    continue

                logger.info(f"Procesando {table_name}. Filas a procesar: {len(df)}")

                # Definir consulta SQL y columnas según la tabla
                if table_name == 'dentfact_doctor':
                    columns = required_columns[table_name]
                    placeholders = ', '.join(['?' for _ in columns])
                    sql = f"INSERT OR IGNORE INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
                    primary_key = 'SPCODE'

                elif table_name == 'dentfact_docpercent':
                    columns = required_columns[table_name]
                    placeholders = ', '.join(['?' for _ in columns])
                    sql = f"INSERT OR IGNORE INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
                    primary_key = ('SPCODE_id', 'CENTRO', 'ESPECIALIDAD')

                elif table_name == 'dentfact_centro':
                    columns = required_columns[table_name]
                    placeholders = ', '.join(['?' for _ in columns])
                    sql = f"INSERT OR IGNORE INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
                    primary_key = 'CENTRO'

                elif table_name == 'dentfact_especialidad':
                    columns = required_columns[table_name]
                    placeholders = ', '.join(['?' for _ in columns])
                    sql = f"INSERT OR IGNORE INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
                    primary_key = 'ESPECIALIDAD'

                elif table_name == 'dentfact_sociedad':
                    columns = required_columns[table_name]
                    placeholders = ', '.join(['?' for _ in columns])
                    sql = f"INSERT OR IGNORE INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
                    primary_key = 'CIF'

                # Procesar cada fila
                for _, row in df.iterrows():
                    try:
                        # Reemplazar valores vacíos o 'nan' por None
                        row = row.replace(['', 'nan', 'None'], np.nan).where(pd.notnull(row), None)

                        # Aplicar valores por defecto para dentfact_docpercent
                        if table_name == 'dentfact_docpercent':
                            row['PORCENTAJE'] = row['PORCENTAJE'] if pd.notnull(row['PORCENTAJE']) else 0
                            row['IRPF'] = row['IRPF'] if pd.notnull(row['IRPF']) else vIRPF

                        # Verificar si el registro ya existe
                        if isinstance(primary_key, tuple):
                            conditions = ' AND '.join([f"{pk} = ?" for pk in primary_key])
                            values = tuple(row[pk] for pk in primary_key)
                        else:
                            conditions = f"{primary_key} = ?"
                            values = (row[primary_key],)

                        cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {conditions}", values)
                        if cursor.fetchone()[0] > 0:
                            result[table_name]['skipped'] += 1
                            logger.debug(f"Registro duplicado en {table_name}: {values}. Saltando.")
                            continue

                        # Preparar datos para inserción
                        insert_values = tuple(row[col] for col in columns)
                        cursor.execute(sql, insert_values)
                        result[table_name]['inserted'] += 1
                        logger.debug(f"Insertado en {table_name}: {insert_values}")

                    except sqlite3.Error as e:
                        error_msg = f"Error al insertar en {table_name} para {values}: {str(e)}"
                        result[table_name]['errors'].append(error_msg)
                        logger.error(error_msg)

                logger.info(f"Completado {table_name}. Insertados: {result[table_name]['inserted']}, Saltados: {result[table_name]['skipped']}, Errores: {len(result[table_name]['errors'])}")

            # Confirmar cambios
            conn.commit()

    except sqlite3.Error as e:
        logger.error(f"Error en la conexión a la base de datos: {str(e)}")
        raise sqlite3.Error(f"Error en la conexión a la base de datos: {str(e)}")

    return result

def format_currency(value):
    if value is None:
        return "0.00 €"
    try:
        return locale.format_string('%.2f €', float(value), grouping=True)
    except ValueError:
        return "0.00 €"

def format_percentage(value):
    if value is None:
        return "0.00%"
    try:
        return f"{float(value) * 100:.2f}%"
    except ValueError:
        return "0.00%"

import pandas as pd
from django.db import connection
from datetime import datetime
from collections import defaultdict

# -------------------------------
# Función genérica para ejecutar SQL
# -------------------------------
def run_sql(query, params=None):
    with connection.cursor() as cursor:
        cursor.execute(query, params or [])
        cols = [col[0] for col in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

# -------------------------------
# Funciones para contar entidades
# -------------------------------
def count_sociedades():
    result = run_sql("SELECT COUNT(*) AS total FROM dentfact_sociedad")
    return result[0]["total"] if result else 0

def count_centros():
    result = run_sql("SELECT COUNT(*) AS total FROM dentfact_centro")
    return result[0]["total"] if result else 0

def count_doctores():
    result = run_sql("SELECT COUNT(*) AS total FROM dentfact_doctor")
    return result[0]["total"] if result else 0

def count_especialidades():
    result = run_sql("SELECT COUNT(*) AS total FROM dentfact_especialidad")
    return result[0]["total"] if result else 0

# -------------------------------
# Función para facturación y gastos mensual
# -------------------------------
def get_facturacion_gastos(year=None):
    year = year or datetime.now().year
    query = """
        SELECT strftime('%m', fecha) AS mes, 
               SUM(total_factura) AS facturacion,
               SUM(gasto) AS gastos
        FROM dentfact_factura_r
        WHERE strftime('%Y', fecha) = %s
        GROUP BY mes
        ORDER BY mes
    """
    rows = run_sql(query, [str(year)])
    meses = [f"{i:02}" for i in range(1, 13)]
    facturacion = []
    gastos = []
    row_dict = {r['mes']: r for r in rows}
    for m in meses:
        facturacion.append(float(row_dict[m]['facturacion']) if m in row_dict else 0.0)
        gastos.append(float(row_dict[m]['gastos']) if m in row_dict else 0.0)
    return facturacion, gastos

# -------------------------------
# Facturación por sociedades (line chart)
# -------------------------------
def get_facturacion_sociedades(year=None):
    year = year or datetime.now().year
    meses = [str(i).zfill(2) for i in range(1, 13)]
    sociedades = run_sql("SELECT id, nombre FROM dentfact_sociedad")
    data = []
    for s in sociedades:
        query = """
            SELECT strftime('%m', fecha) AS mes, SUM(total_factura) AS total
            FROM dentfact_factura_r
            WHERE strftime('%Y', fecha) = %s AND sociedad_id = %s
            GROUP BY mes
        """
        rows = run_sql(query, [str(year), s['id']])
        row_dict = {r['mes']: float(r['total']) for r in rows}
        data.append({
            "label": s['nombre'],
            "data": [row_dict.get(m, 0.0) for m in meses]
        })
    return data

# -------------------------------
# Facturación por centros y dentistas (bar chart apilado)
# -------------------------------
def get_facturacion_categorias(tabla="centro", year=None):
    """
    tabla = "centro" o "doctor"
    """
    year = year or datetime.now().year
    meses = [str(i).zfill(2) for i in range(1, 13)]
    if tabla == "centro":
        entidades = run_sql("SELECT id, nombre FROM dentfact_centro")
    elif tabla == "doctor":
        entidades = run_sql("SELECT id, nombre FROM dentfact_doctor")
    else:
        raise ValueError("tabla debe ser 'centro' o 'doctor'")

    series = [{"name": m, "data": []} for m in meses]
    categories = [e['nombre'] for e in entidades]

    for e in entidades:
        query = f"""
            SELECT strftime('%m', fecha) AS mes, SUM(total_factura) AS total
            FROM dentfact_factura_r
            WHERE strftime('%Y', fecha) = %s AND {tabla}_id = %s
            GROUP BY mes
        """
        rows = run_sql(query, [str(year), e['id']])
        row_dict = {r['mes']: float(r['total']) for r in rows}
        for i, m in enumerate(meses):
            series[i]["data"].append(row_dict.get(m, 0.0))
    return {"categories": categories, "series": series}

# -------------------------------
# Facturación por especialidades (pie chart)
# -------------------------------
def get_facturacion_especialidades(year=None):
    year = year or datetime.now().year
    especialidades = run_sql("SELECT id, nombre FROM dentfact_especialidad")
    data = []
    for e in especialidades:
        query = """
            SELECT SUM(total_factura) AS total
            FROM dentfact_factura_r
            WHERE strftime('%Y', fecha) = %s AND especialidad_id = %s
        """
        rows = run_sql(query, [str(year), e['id']])
        total = float(rows[0]["total"]) if rows and rows[0]["total"] else 0.0
        data.append({"name": e["nombre"], "y": total})
    return data

def df2tDB_verifactu(df: pd.DataFrame, db_path: str) -> dict:
    """
    Inserta un DataFrame en la tabla dentfact_factura_v, respetando el modelo Factura_V.
    Tolerante a mayúsculas/minúsculas y optimizado con executemany.
    """
    logger = logging.getLogger(__name__)
    result = {'inserted': 0, 'skipped': 0, 'errors': []}

    if not isinstance(df, pd.DataFrame) or df.empty:
        logger.warning("DataFrame vacío o inválido")
        return result

    # Normalizar nombres de columnas a minúsculas
    df = df.rename(columns=str.lower)

    # Columnas requeridas (en minúsculas)
    required_cols = ['factura', 'qr_code', 'qr_base64', 'hash', 'previous_hash', 'sif_id', 'xml']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        logger.error(f"Faltan columnas requeridas: {missing_cols}")
        raise ValueError(f"Faltan columnas requeridas: {missing_cols}")

    # Asegurar tipos correctos y manejar NaN
    df = df.copy()
    df['factura'] = df['factura'].astype(str)
    df['qr_code'] = df['qr_code'].fillna('').astype(str)
    df['qr_base64'] = df['qr_base64'].fillna('').astype(str)
    df['sif_id'] = df['sif_id'].fillna('').astype(str)
    df['xml'] = df['xml'].fillna('').astype(str)

    # Validar y corregir hashes
    hash_pattern = r'^[0-9a-fA-F]{64}$'
    for col in ['hash', 'previous_hash']:
        mask_invalid = ~df[col].astype(str).str.match(hash_pattern, na=True)
        if mask_invalid.any():
            invalid_examples = df.loc[mask_invalid, col].head(5).tolist()
            logger.warning(f"Valores inválidos en {col}: {invalid_examples}")
            df.loc[mask_invalid, col] = '0' * 64

    # Convertir NaN a None para SQLite
    df = df.where(pd.notnull(df), None)

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Asegurar índices únicos para evitar duplicados
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_factura_v_unique 
                ON dentfact_factura_v (factura)
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_sif_id_unique 
                ON dentfact_factura_v (sif_id) WHERE sif_id != ''
            """)

            # Preparar datos para inserción masiva
            data_to_insert = []
            skipped_due_to_duplicate = 0

            for row in df.itertuples(index=False):
                # Verificar duplicado por factura o sif_id (no vacío)
                cursor.execute("""
                    SELECT 1 FROM dentfact_factura_v 
                    WHERE factura = ? OR (sif_id = ? AND sif_id != '')
                """, (row.factura, row.sif_id))
                if cursor.fetchone():
                    skipped_due_to_duplicate += 1
                    continue

                data_to_insert.append((
                    row.factura,
                    row.qr_code,
                    row.qr_base64,
                    row.hash,
                    row.previous_hash,
                    row.sif_id,
                    row.xml
                ))

            if data_to_insert:
                cursor.executemany("""
                    INSERT INTO dentfact_factura_v 
                    (factura, qr_code, qr_base64, hash, previous_hash, sif_id, xml)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, data_to_insert)
                inserted = cursor.rowcount
            else:
                inserted = 0

            conn.commit()

            result['inserted'] = inserted
            result['skipped'] = skipped_due_to_duplicate
            logger.info(f"Veri*Factu → Insertados: {inserted}, Saltados (duplicados): {skipped_due_to_duplicate}")

            return result

    except sqlite3.Error as e:
        logger.error(f"Error SQLite en df2tDB_verifactu: {e}", exc_info=True)
        result['errors'].append(str(e))
        return result
    except Exception as e:
        logger.error(f"Error inesperado en df2tDB_verifactu: {e}", exc_info=True)
        result['errors'].append(str(e))
        return result


def is_valid_decimal(value):
    """Verifica si un valor puede convertirse a Decimal."""
    if value is None or value == '' or value == ' ' or value == '-' or value == 'NULL':
        return False
    try:
        Decimal(str(value))
        return True
    except (InvalidOperation, ValueError, TypeError):
        return False

def fix_docpercent_decimals():
    """
    Corrige los valores no numéricos en IRPF y PORCENTAJE
    convirtiéndolos a '0.00'.
    """
    if not os.path.exists(DB_PATH):
        print(f"❌ Error: No se encontró la base de datos en { sqlite3_dbpath}")
        return False
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        print("🔍 Analizando tabla dentfact_docpercent...")
        
        # Obtener todos los registros
        cursor.execute("SELECT id, IRPF, PORCENTAJE FROM dentfact_docpercent")
        rows = cursor.fetchall()
        
        print(f"📊 Total de registros encontrados: {len(rows)}")
        
        fixed_count = 0
        errors = []
        
        for row in rows:
            record_id, irpf, porcentaje = row
            needs_update = False
            new_irpf = irpf
            new_porcentaje = porcentaje
            
            # Verificar IRPF
            if not is_valid_decimal(irpf):
                new_irpf = '0.00'
                needs_update = True
                errors.append(f"ID {record_id}: IRPF inválido '{irpf}' → '0.00'")
            
            # Verificar PORCENTAJE
            if not is_valid_decimal(porcentaje):
                new_porcentaje = '0.00'
                needs_update = True
                errors.append(f"ID {record_id}: PORCENTAJE inválido '{porcentaje}' → '0.00'")
            
            # Actualizar si es necesario
            if needs_update:
                cursor.execute(
                    "UPDATE dentfact_docpercent SET IRPF = ?, PORCENTAJE = ? WHERE id = ?",
                    (new_irpf, new_porcentaje, record_id)
                )
                fixed_count += 1
        
        # Confirmar cambios
        conn.commit()
        
        print(f"\n✅ Corrección completada:")
        print(f"   - Registros corregidos: {fixed_count}")
        print(f"   - Registros sin cambios: {len(rows) - fixed_count}")
        
        if errors:
            print(f"\n📝 Detalles de correcciones:")
            for error in errors[:10]:  # Mostrar solo los primeros 10
                print(f"   {error}")
            if len(errors) > 10:
                print(f"   ... y {len(errors) - 10} más")
        
        conn.close()
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Error de base de datos: {e}")
        return False
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        return False


def verify_docpercent_data():
    """Verifica que todos los valores sean decimales válidos."""
    if not os.path.exists(DB_PATH):
        print(f"❌ Error: No se encontró la base de datos en {sqlite3_dbpath}")
        return False
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        print("🔍 Verificando datos en dentfact_docpercent...")
        
        cursor.execute("SELECT id, SPCODE_id, ESPECIALIDAD, CENTRO, IRPF, PORCENTAJE FROM dentfact_docpercent")
        rows = cursor.fetchall()
        
        print(f"📊 Total de registros: {len(rows)}")
        
        invalid_records = []
        
        for row in rows:
            record_id, spcode, especialidad, centro, irpf, porcentaje = row
            
            try:
                # Intentar convertir a Decimal
                if irpf is not None and irpf != '':
                    Decimal(str(irpf))
                if porcentaje is not None and porcentaje != '':
                    Decimal(str(porcentaje))
            except (InvalidOperation, ValueError, TypeError) as e:
                invalid_records.append({
                    'id': record_id,
                    'spcode': spcode,
                    'especialidad': especialidad,
                    'centro': centro,
                    'irpf': irpf,
                    'porcentaje': porcentaje,
                    'error': str(e)
                })
        
        if invalid_records:
            print(f"\n⚠️  Se encontraron {len(invalid_records)} registros con valores inválidos:")
            for rec in invalid_records[:5]:
                print(f"   ID {rec['id']}: IRPF='{rec['irpf']}', PORCENTAJE='{rec['porcentaje']}'")
            if len(invalid_records) > 5:
                print(f"   ... y {len(invalid_records) - 5} más")
            conn.close()
            return False
        else:
            print("\n✅ Todos los registros tienen valores decimales válidos")
            
            # Mostrar algunos ejemplos
            print("\n📋 Ejemplos de registros válidos:")
            for row in rows[:5]:
                record_id, spcode, especialidad, centro, irpf, porcentaje = row
                print(f"   ID {record_id}: IRPF={irpf}, PORCENTAJE={porcentaje}")
            
            conn.close()
            return True
        
    except sqlite3.Error as e:
        print(f"❌ Error de base de datos: {e}")
        return False
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        return False
