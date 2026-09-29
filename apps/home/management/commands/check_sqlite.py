# apps/home/management/commands/check_sqlite.py
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Ejecuta PRAGMA integrity_check sobre la base de datos SQLite'

    def handle(self, *args, **options):
        self.stdout.write('Ejecutando PRAGMA integrity_check...')

        with connection.cursor() as cursor:
            cursor.execute('PRAGMA integrity_check;')
            result = cursor.fetchone()

        if result and result[0] == 'ok':
            self.stdout.write(self.style.SUCCESS('Integridad OK.'))
        else:
            self.stderr.write(self.style.ERROR(f'Integridad FALLIDA: {result}'))
            raise SystemExit(1)