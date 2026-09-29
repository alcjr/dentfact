from django.apps import AppConfig

class HomeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.home'

    def ready(self):
        # Importar la función después para evitar problemas de importación circular
        from apps.home.db import optimize_sqlite
        optimize_sqlite()