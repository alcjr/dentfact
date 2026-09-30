from django.apps import AppConfig


class HomeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.home'

    def ready(self):
        # Solo registra el receptor de la señal; no abre conexiones aquí.
        from apps.home import db  # noqa: F401