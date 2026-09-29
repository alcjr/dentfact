# apps/home/config.py
from functools import lru_cache
from django.apps import apps


@lru_cache(maxsize=1)
def get_configuracion():
    Configuracion = apps.get_model('home', 'Configuracion')
    return Configuracion.objects.first()