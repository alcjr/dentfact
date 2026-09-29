from django.db import connection

def optimize_sqlite():
    """Optimiza la configuración de SQLite para mejorar la durabilidad y rendimiento."""
    cursor = connection.cursor()
    # Configurar el modo WAL (Write-Ahead Logging) para mejor concurrencia
    cursor.execute('PRAGMA journal_mode=WAL;')
    # FULL para máxima seguridad, NORMAL para un balance, OFF para máximo rendimiento
    cursor.execute('PRAGMA synchronous=NORMAL;')
    # Almacenar tablas temporales en memoria
    cursor.execute('PRAGMA temp_store=MEMORY;')
    # Aumentar el tamaño de caché
    cursor.execute('PRAGMA cache_size=-10000;')  # Aproximadamente 10MB
    # Verificar la integridad de la base de datos
    cursor.execute('PRAGMA integrity_check;')
    result = cursor.fetchone()
    return result[0] == 'ok'