# apps/home/management/commands/init_factura.py
import logging

from django.core.management.base import BaseCommand

from apps.home import views_factura as vf


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Ejecuta el pipeline completo de facturación (init_factura)'

    def handle(self, *args, **options):
        result = vf.init_factura()
        if result['success']:
            self.stdout.write(self.style.SUCCESS(result['message']))
            for name, df in result['dataframes'].items():
                self.stdout.write(f'  {name}: {len(df)} filas')
        else:
            self.stderr.write(self.style.ERROR(result['message']))
            raise SystemExit(1)