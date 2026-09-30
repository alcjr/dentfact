from django.db.backends.signals import connection_created
from django.dispatch import receiver


@receiver(connection_created)
def optimize_sqlite(sender, connection, **kwargs):
    """Aplica PRAGMAs solo cuando se abre una conexión SQLite."""
    if connection.vendor != 'sqlite':
        return
    cursor = connection.cursor()
    cursor.execute('PRAGMA journal_mode=WAL;')
    cursor.execute('PRAGMA synchronous=NORMAL;')
    # ...el resto de tus PRAGMA actuales