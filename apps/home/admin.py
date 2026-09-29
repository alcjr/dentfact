from django.contrib import admin
from django.contrib.admin.sites import site
from .models import Factura_R, Factura_C, Factura_D, Doctor, Importes, Centro, Sociedad, Especialidad, Docpercent

# Cambiar el título del sitio de administración
admin.site.site_header = "Panel de administración"
admin.site.site_title = "Administración"
admin.site.index_title = "Bienvenido al panel de administración"


admin.site.register(Doctor)
admin.site.register(Importes)

admin.site.register(Factura_R)
admin.site.register(Factura_D)
admin.site.register(Factura_C)
admin.site.register(Docpercent)
admin.site.register(Sociedad)
admin.site.register(Centro)
admin.site.register(Especialidad)





