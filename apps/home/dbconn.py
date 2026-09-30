"""
apps/home/dbconn.py
Acceso a PostgreSQL para la capa pandas de DENTFACT.

Sustituye a las funciones sqlite3 de views_utils.py conservando sus firmas.
El argumento ``db_path`` se mantiene por compatibilidad y se IGNORA: la
conexión sale siempre de settings.DATABASES['default'].

Requisitos:  pip install sqlalchemy "psycopg[binary]"
"""
import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from django.conf import settings
from sqlalchemy import create_engine, inspect, text
from sqlalchemy import types as sqltypes
from sqlalchemy.engine import URL
from sqlalchemy.exc import NoSuchTableError

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# Conexión
# ------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_engine():
    db = settings.DATABASES['default']
    if 'postgresql' not in db['ENGINE']:
        raise RuntimeError("dbconn.py solo funciona con PostgreSQL (DB_ENGINE distinto de 'sqlite').")
    url = URL.create(
        'postgresql+psycopg',
        username=db['USER'], password=db['PASSWORD'],
        host=db['HOST'], port=int(db['PORT']), database=db['NAME'],
    )
    return create_engine(url, pool_pre_ping=True)


# ------------------------------------------------------------------------------
# Utilidades internas
# ------------------------------------------------------------------------------
def _ident(name: str) -> str:
    """Identificador SQL entre comillas dobles (respeta mayúsculas) y validado."""
    name = str(name)
    if not name or not name.replace('_', '').isalnum():
        raise ValueError(f"Identificador SQL no válido: {name!r}")
    return '"' + name + '"'


def _table_columns(conn, table_name: str) -> Dict[str, dict]:
    try:
        cols = inspect(conn).get_columns(table_name)
    except NoSuchTableError:
        raise ValueError(f"La tabla {table_name} no existe")
    if not cols:
        raise ValueError(f"La tabla {table_name} no existe")
    return {c['name']: c for c in cols}


def _kind(col: dict) -> str:
    t = col['type']
    if isinstance(t, sqltypes.String):
        return 'text'
    if isinstance(t, (sqltypes.Integer, sqltypes.Numeric)):
        return 'num'
    return 'other'


def _model_defaults(table_name: str) -> Dict[str, Any]:
    """Defaults de Python de los modelos Django (no existen como DEFAULT en la BD)."""
    from django.apps import apps
    for m in apps.get_models():
        if m._meta.db_table == table_name:
            return {f.column: f.get_default() for f in m._meta.concrete_fields if f.has_default()}
    return {}


def _py(v: Any) -> Any:
    return v.item() if isinstance(v, np.generic) else v


def _isnull(v: Any) -> bool:
    return v is None or (not isinstance(v, str) and pd.isna(v))


def _to_text(v: Any) -> Optional[str]:
    if _isnull(v):
        return None
    if isinstance(v, float):
        return str(round(v, 6))
    return v if isinstance(v, str) else str(v)


def _prepare_frame(df: pd.DataFrame, meta: Dict[str, dict], table_name: str) -> pd.DataFrame:
    """
    Adapta el DataFrame a los tipos y longitudes reales de la tabla PostgreSQL.
    - Descarta columnas que no existen en la tabla (con aviso).
    - Texto: convierte a str, NaN -> NULL (si la columna es NOT NULL: default del
      modelo Django, o '' si no tiene).
    - Numérico: to_numeric, NaN -> NULL (si NOT NULL: default del modelo, o 0).
    - Columnas NOT NULL que faltan en el DataFrame: se añaden con el default del modelo.
    - Si algún texto supera el varchar(n) de la tabla, LANZA ValueError
      (nunca trunca datos de facturación en silencio).
    """
    valid = [c for c in df.columns if c in meta]
    dropped = [c for c in df.columns if c not in meta]
    if dropped:
        logger.warning("Columnas que no existen en %s y se ignoran: %s", table_name, dropped)
    out = df[valid].copy().astype(object)

    # Columnas NOT NULL ausentes en el DataFrame: se rellenan con el default del modelo.
    defaults = _model_defaults(table_name)
    for c, m in meta.items():
        if c not in out.columns and not m.get('nullable', True) and defaults.get(c) is not None:
            out[c] = defaults[c]
            valid.append(c)

    problems: List[str] = []
    for c in valid:
        m = meta[c]
        kind = _kind(m)
        nullable = m.get('nullable', True)
        if kind == 'text':
            col = out[c].map(_to_text)
            if not nullable:
                fill = defaults.get(c)
                fill = '' if fill is None else str(fill)
                col = col.map(lambda v: fill if _isnull(v) else v)
            maxlen = getattr(m['type'], 'length', None)
            if maxlen:
                longest = max((len(v) for v in col if isinstance(v, str)), default=0)
                if longest > maxlen:
                    problems.append(f"{table_name}.{c}: máximo real {longest} > varchar({maxlen})")
            out[c] = col
        elif kind == 'num':
            col = pd.to_numeric(out[c], errors='coerce')
            if not nullable:
                fill = defaults.get(c)
                col = col.fillna(0 if fill is None else float(fill))
            out[c] = col.astype(object).where(col.notna(), None)
    if problems:
        raise ValueError("Datos demasiado largos para la tabla: " + "; ".join(problems))
    return out.astype(object).where(pd.notnull(out), None)


def _insert_sql(table_name: str, columns: List[str],
                pk_cols: Optional[List[str]] = None, update: bool = False) -> str:
    cols_sql = ', '.join(_ident(c) for c in columns)
    params_sql = ', '.join(f':p{i}' for i in range(len(columns)))
    sql = f'INSERT INTO {_ident(table_name)} ({cols_sql}) VALUES ({params_sql})'
    if update and pk_cols:
        pk_sql = ', '.join(_ident(c) for c in pk_cols)
        sets = ', '.join(f'{_ident(c)} = EXCLUDED.{_ident(c)}' for c in columns if c not in pk_cols)
        if sets:
            return sql + f' ON CONFLICT ({pk_sql}) DO UPDATE SET {sets}'
        return sql + f' ON CONFLICT ({pk_sql}) DO NOTHING'
    return sql + ' ON CONFLICT DO NOTHING'


def _records(df: pd.DataFrame, columns: List[str]) -> List[dict]:
    return [
        {f'p{i}': _py(v) for i, v in enumerate(row)}
        for row in df[columns].itertuples(index=False, name=None)
    ]


def _insert_many(conn, table_name, df, columns, pk_cols=None, update=False, chunk=2000) -> int:
    if df.empty:
        return 0
    sql = text(_insert_sql(table_name, columns, pk_cols, update))
    recs = _records(df, columns)
    for i in range(0, len(recs), chunk):
        conn.execute(sql, recs[i:i + chunk])
    return len(recs)


# ------------------------------------------------------------------------------
# Lectura
# ------------------------------------------------------------------------------
def table2df(db_path, tabla_nombre):
    """Carga una tabla completa como DataFrame (db_path se ignora)."""
    try:
        with get_engine().connect() as conn:
            return pd.read_sql_query(text(f'SELECT * FROM {_ident(tabla_nombre)}'), conn)
    except Exception as e:
        logger.error("Error al cargar la tabla %s: %s", tabla_nombre, e)
        return pd.DataFrame()


def load_table_to_dataframe(pathDB=None, dbTable: str = None) -> pd.DataFrame:
    """Igual que table2df, con aviso si la tabla no existe o está vacía."""
    try:
        with get_engine().connect() as conn:
            if not inspect(conn).has_table(dbTable):
                logger.warning("La tabla %s no existe", dbTable)
                return pd.DataFrame()
            df = pd.read_sql_query(text(f'SELECT * FROM {_ident(dbTable)}'), conn)
        if df.empty:
            logger.warning("La tabla %s está vacía.", dbTable)
        else:
            logger.info("Tabla %s cargada: %s filas, %s columnas.", dbTable, len(df), len(df.columns))
        return df
    except Exception as e:
        logger.error("Error inesperado al cargar la tabla %s: %s", dbTable, e, exc_info=True)
        return pd.DataFrame()


def get_table_info(db_path, table_name):
    """Metadatos de una tabla. Misma estructura de retorno que la versión SQLite."""
    with get_engine().connect() as conn:
        insp = inspect(conn)
        if not insp.has_table(table_name):
            raise LookupError(f"La tabla {table_name} no existe")
        row_count = conn.execute(text(f'SELECT COUNT(*) FROM {_ident(table_name)}')).scalar()
        pk = set(insp.get_pk_constraint(table_name).get('constrained_columns') or [])
        cols = insp.get_columns(table_name)
    logger.info("Tabla '%s': %s registros, %s columnas", table_name, row_count, len(cols))
    return {
        "table_name": table_name,
        "row_count": row_count,
        "columns": [
            {"name": c['name'], "type": str(c['type']),
             "not_null": 0 if c.get('nullable', True) else 1,
             "default": c.get('default'), "pk": 1 if c['name'] in pk else 0}
            for c in cols
        ],
    }


# ------------------------------------------------------------------------------
# Escritura genérica
# ------------------------------------------------------------------------------
def df2tDB(df, db_path=None, pk_field: str = None, table_name: str = None,
           overwrite: bool = False) -> dict:
    """
    Guarda un DataFrame en una tabla, sin duplicar por pk_field.
    overwrite=False: omite las filas cuya clave ya existe (comportamiento anterior).
    overwrite=True : actualiza las existentes (ON CONFLICT DO UPDATE).
    Devuelve {'inserted': int, 'skipped': int} (+ 'error' si algo falla).
    """
    result = {'inserted': 0, 'skipped': 0}
    if not isinstance(df, pd.DataFrame):
        logger.error("df2tDB: se esperaba un DataFrame, tipo recibido %s", type(df))
        return result
    if df.empty:
        logger.warning("df2tDB: DataFrame vacío, no se inserta nada.")
        return result

    try:
        logger.info("df2tDB: %s filas -> %s", len(df), table_name)
        with get_engine().begin() as conn:
            meta = _table_columns(conn, table_name)
            data = _prepare_frame(df, meta, table_name)

            has_pk = pk_field in data.columns
            if has_pk:
                dups = int(data[pk_field].duplicated().sum())
                if dups:
                    logger.warning("Se eliminan %s duplicados internos por %s.", dups, pk_field)
                    data = data.drop_duplicates(subset=[pk_field], keep='first')
                if not overwrite:
                    existing = {str(r[0]) for r in conn.execute(
                        text(f'SELECT {_ident(pk_field)} FROM {_ident(table_name)}'))}
                    before = len(data)
                    data = data[~data[pk_field].astype(str).isin(existing)]
                    result['skipped'] = before - len(data)

            if data.empty:
                logger.info("df2tDB: no hay filas nuevas para insertar.")
                return result

            result['inserted'] = _insert_many(
                conn, table_name, data, list(data.columns),
                pk_cols=[pk_field] if has_pk else None, update=overwrite and has_pk)
        return result
    except Exception as e:
        logger.error("Error en df2tDB (%s): %s", table_name, e, exc_info=True)
        return {'inserted': 0, 'skipped': 0, 'error': str(e)}


def dfi2tdb(df_importes, db_path=None):
    """
    Regenera dentfact_importes con el contenido del DataFrame.
    Antes se hacía DROP + CREATE; ahora TRUNCATE ... RESTART IDENTITY dentro de
    una transacción, para no destruir la tabla que gestiona Django. Si algo
    falla, la tabla queda como estaba.
    """
    required_columns = [
        "CENTRO", "N_CENTRO", "DOCTOR", "ESPECIALIDAD", "COLABORADOR",
        "COLEGIADO", "CIF", "LIQUIDACION", "L_DESDE", "L_HASTA", "PP_BASE",
        "PP_LIQUIDO", "PM_BASE", "PM_LIQUIDO", "P_BASE", "P_LIQUIDO",
        "R_BASE", "R_LIQUIDO", "C_FIJA", "C_TURNO", "PPA_BASE", "PPA_LIQUIDO",
        "PMA_BASE", "PMA_LIQUIDO", "PA_BASE", "PA_LIQUIDO", "HHRR", "BRUTO",
        "NETO", "SPCODE", "ANNO", "FECHA",
    ]
    table = 'dentfact_importes'
    try:
        df = df_importes.copy()
        for col in required_columns:
            if col not in df.columns:
                df[col] = ''
            df[col] = df[col].map(lambda x: str(x).strip() if pd.notnull(x) else '')
        df = df[required_columns]
        df_rows = len(df)

        n_dups = int(df.duplicated(keep='first').sum())
        if n_dups:
            logger.warning("dfi2tdb: %s filas duplicadas estrictas eliminadas.", n_dups)
            df = df.drop_duplicates(keep='first')

        with get_engine().begin() as conn:
            meta = _table_columns(conn, table)
            missing = [c for c in required_columns if c not in meta]
            if missing:
                logger.error("La tabla %s no tiene las columnas %s: se ignoran (añádelas al modelo Importes).",
                             table, missing)
            usable = [c for c in required_columns if c in meta]
            data = _prepare_frame(df[usable], meta, table)   # puede lanzar ValueError (antes del TRUNCATE)
            conn.execute(text(f'TRUNCATE TABLE {_ident(table)} RESTART IDENTITY'))
            inserted = _insert_many(conn, table, data, usable)

        logger.info("dfi2tdb: entrada=%s, insertados=%s", df_rows, inserted)
        return {"df_rows": df_rows, "inserted": inserted,
                "skipped": df_rows - inserted, "not_inserted": pd.DataFrame(columns=required_columns)}
    except Exception as e:
        logger.error("Error en dfi2tdb: %s", e, exc_info=True)
        return {"df_rows": len(df_importes), "inserted": 0, "skipped": 0,
                "not_inserted": df_importes, "error": str(e)}


# ------------------------------------------------------------------------------
# Tablas maestras
# ------------------------------------------------------------------------------
_UPD_TABLES = {
    'dentfact_doctor': (
        ['SPCODE', 'DOCTOR', 'ESPECIALIDAD', 'COLABORADOR', 'COLEGIADO', 'CIF',
         'I_APELLIDO', 'II_APELLIDO', 'NOMBRE', 'DNI', 'GASTOS', 'ESTADO',
         'EMAIL', 'DIRECCION', 'CIUDAD', 'POSTAL', 'TELEFONO', 'CUENTA',
         'GABINETE_01', 'GABINETE_02'],
        ['SPCODE']),
    'dentfact_docpercent': (
        ['SPCODE_id', 'CENTRO', 'ESPECIALIDAD', 'PORCENTAJE', 'IRPF'],
        ['SPCODE_id', 'CENTRO', 'ESPECIALIDAD']),
    'dentfact_centro': (
        ['CENTRO', 'N_CENTRO', 'DIRECCION', 'POBLACION', 'PROVINCIA',
         'POSTAL', 'EMAIL', 'WWW', 'DESCRIPCION'],
        ['CENTRO']),
    'dentfact_especialidad': (['ESPECIALIDAD', 'DESCRIPCION'], ['ESPECIALIDAD']),
    'dentfact_sociedad': (
        ['CIF', 'SOCIEDAD', 'DESCRIPCION_SOC', 'DIRECCION_SOC',
         'PROVINCIA_SOC', 'POSTAL_SOC', 'REPRESENTANTE', 'NIF_REP'],
        ['CIF']),
}


def updTables(df_doctor=None, df_docpercent=None, df_centro=None,
              df_especialidad=None, df_sociedad=None,
              db_path=None, vIRPF: float = 0.15) -> dict:
    """
    Inserta en las tablas maestras las filas cuya clave no exista todavía.
    Se comprueba la existencia por SELECT (igual que antes) porque, p. ej.,
    dentfact_sociedad ya no tiene PRIMARY KEY(CIF) en PostgreSQL.
    """
    result = {t: {'inserted': 0, 'skipped': 0, 'errors': []} for t in _UPD_TABLES}
    dataframes = {
        'dentfact_doctor': df_doctor, 'dentfact_docpercent': df_docpercent,
        'dentfact_centro': df_centro, 'dentfact_especialidad': df_especialidad,
        'dentfact_sociedad': df_sociedad,
    }

    for table, df in dataframes.items():
        if df is not None and not df.empty:
            missing = [c for c in _UPD_TABLES[table][0] if c not in df.columns]
            if missing:
                raise ValueError(f"Faltan columnas en {table}: {missing}")

    with get_engine().begin() as conn:
        for table, df in dataframes.items():
            if df is None or df.empty:
                logger.info("Sin DataFrame para %s. Saltando.", table)
                continue
            columns, pk_cols = _UPD_TABLES[table]
            try:
                meta = _table_columns(conn, table)
                work = df[columns].copy().replace(['', 'nan', 'None'], np.nan)
                if table == 'dentfact_docpercent':
                    work['PORCENTAJE'] = pd.to_numeric(work['PORCENTAJE'], errors='coerce').fillna(0)
                    work['IRPF'] = pd.to_numeric(work['IRPF'], errors='coerce').fillna(vIRPF)
                null_pk = work[pk_cols].isna().any(axis=1)
                if null_pk.any():
                    logger.warning("%s: %s filas con clave nula, se saltan.", table, int(null_pk.sum()))
                    result[table]['skipped'] += int(null_pk.sum())
                    work = work[~null_pk]
                data = _prepare_frame(work, meta, table)
            except ValueError as e:
                result[table]['errors'].append(str(e))
                logger.error("%s: %s", table, e)
                continue

            exists_sql = text(
                f'SELECT 1 FROM {_ident(table)} WHERE ' +
                ' AND '.join(f'{_ident(pk)} = :k{i}' for i, pk in enumerate(pk_cols)) + ' LIMIT 1')
            insert_sql = text(_insert_sql(table, columns))

            for rec in data[columns].to_dict('records'):
                rec = {k: _py(v) for k, v in rec.items()}
                keys = tuple(rec[pk] for pk in pk_cols)
                try:
                    with conn.begin_nested():
                        if conn.execute(exists_sql, {f'k{i}': v for i, v in enumerate(keys)}).first():
                            result[table]['skipped'] += 1
                            continue
                        conn.execute(insert_sql, {f'p{i}': rec[c] for i, c in enumerate(columns)})
                        result[table]['inserted'] += 1
                except Exception as e:
                    msg = f"Error al insertar en {table} para {keys}: {e}"
                    result[table]['errors'].append(msg)
                    logger.error(msg)
            logger.info("%s: insertados=%s saltados=%s errores=%s", table,
                        result[table]['inserted'], result[table]['skipped'], len(result[table]['errors']))
    return result


def clean_duplicates(db_path=None, tables: List[Dict[str, Any]] = None, keep: str = 'first'):
    """Elimina duplicados por clave (usa ctid en lugar de rowid)."""
    if keep not in ('first', 'last'):
        raise ValueError(f"Criterio 'keep' inválido: {keep}")
    default_tables = [
        {'table': 'dentfact_especialidad', 'pk_cols': ['ESPECIALIDAD'], 'order': 1},
        {'table': 'dentfact_centro', 'pk_cols': ['CENTRO'], 'order': 2},
        {'table': 'dentfact_sociedad', 'pk_cols': ['ID_SOC'], 'unique_cols': ['CIF'], 'order': 3},
        {'table': 'dentfact_doctor', 'pk_cols': ['SPCODE'], 'order': 4},
    ]
    tables = sorted(tables or default_tables, key=lambda x: x['order'])
    results = {t['table']: {'duplicates_found': 0, 'deleted': 0, 'errors': 0} for t in tables}
    op = '>' if keep == 'first' else '<'

    with get_engine().begin() as conn:
        for cfg in tables:
            t = cfg['table']
            cols = cfg.get('unique_cols', cfg['pk_cols'])
            cols_sql = ', '.join(_ident(c) for c in cols)
            try:
                with conn.begin_nested():
                    dups = pd.read_sql_query(text(
                        f'SELECT {cols_sql}, COUNT(*) AS n FROM {_ident(t)} '
                        f'GROUP BY {cols_sql} HAVING COUNT(*) > 1'), conn)
                    results[t]['duplicates_found'] = len(dups)
                    if dups.empty:
                        continue
                    cond = ' AND '.join(f'a.{_ident(c)} IS NOT DISTINCT FROM b.{_ident(c)}' for c in cols)
                    res = conn.execute(text(
                        f'DELETE FROM {_ident(t)} a USING {_ident(t)} b '
                        f'WHERE a.ctid {op} b.ctid AND {cond}'))
                    results[t]['deleted'] = res.rowcount
                    logger.info("Eliminados %s duplicados en %s.", res.rowcount, t)
            except Exception as e:
                results[t]['errors'] += 1
                logger.error("Error limpiando duplicados en %s: %s", t, e)
    return results


# ------------------------------------------------------------------------------
# Veri*Factu
# ------------------------------------------------------------------------------
def df2tDB_verifactu(df: pd.DataFrame, db_path=None) -> dict:
    """
    Inserta en dentfact_factura_v (columnas en minúsculas). Se conserva el ORDEN
    del DataFrame (importa para el encadenamiento de huellas).
    """
    result = {'inserted': 0, 'skipped': 0, 'errors': []}
    if not isinstance(df, pd.DataFrame) or df.empty:
        logger.warning("DataFrame vacío o inválido")
        return result

    df = df.rename(columns=str.lower)
    required = ['factura', 'qr_code', 'qr_base64', 'hash', 'previous_hash', 'sif_id', 'xml']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {missing}")

    df = df[required].copy()
    df['factura'] = df['factura'].astype(str)
    for c in ('qr_code', 'qr_base64', 'sif_id', 'xml'):
        df[c] = df[c].fillna('').astype(str)
    pattern = r'^[0-9a-fA-F]{64}$'
    for c in ('hash', 'previous_hash'):
        bad = ~df[c].astype(str).str.match(pattern, na=True)
        if bad.any():
            logger.warning("Valores inválidos en %s: %s", c, df.loc[bad, c].head(5).tolist())
            df.loc[bad, c] = '0' * 64

    table = 'dentfact_factura_v'
    try:
        with get_engine().begin() as conn:
            meta = _table_columns(conn, table)
            data = _prepare_frame(df, meta, table)

            facts = data['factura'].tolist()
            sifs = [s for s in data['sif_id'].tolist() if s]
            existing_f = {r[0] for r in conn.execute(
                text(f'SELECT {_ident("factura")} FROM {_ident(table)} WHERE {_ident("factura")} = ANY(:v)'),
                {'v': facts})}
            existing_s = set()
            if sifs:
                existing_s = {r[0] for r in conn.execute(
                    text(f'SELECT {_ident("sif_id")} FROM {_ident(table)} WHERE {_ident("sif_id")} = ANY(:v)'),
                    {'v': sifs})}

            keep_rows, seen_f, seen_s = [], set(), set()
            for row in data.itertuples(index=True):
                f, s = row.factura, row.sif_id
                if f in existing_f or f in seen_f or (s and (s in existing_s or s in seen_s)):
                    result['skipped'] += 1
                    continue
                seen_f.add(f)
                if s:
                    seen_s.add(s)
                keep_rows.append(row.Index)

            new = data.loc[keep_rows]
            result['inserted'] = _insert_many(conn, table, new, required)
        logger.info("Veri*Factu → insertados=%s, saltados=%s", result['inserted'], result['skipped'])
        return result
    except Exception as e:
        logger.error("Error en df2tDB_verifactu: %s", e, exc_info=True)
        result['errors'].append(str(e))
        return result


# ------------------------------------------------------------------------------
# Utilidades de mantenimiento de docpercent (ya no aplican en PostgreSQL)
# ------------------------------------------------------------------------------
def fix_docpercent_decimals():
    """En PostgreSQL IRPF/PORCENTAJE son numeric: no pueden contener texto inválido."""
    logger.info("fix_docpercent_decimals: no aplica con columnas numeric en PostgreSQL.")
    return True


def verify_docpercent_data():
    with get_engine().connect() as conn:
        nulos = conn.execute(text(
            'SELECT COUNT(*) FROM "dentfact_docpercent" WHERE "IRPF" IS NULL OR "PORCENTAJE" IS NULL')).scalar()
    logger.info("verify_docpercent_data: %s registros con IRPF/PORCENTAJE nulos.", nulos)
    return True
