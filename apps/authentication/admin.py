
from django.contrib import admin

class MyAdminSite(admin.AdminSite):
    site_header = "Mi Panel de Administración"
    site_title = "Administración Personalizada"
    index_title = "Bienvenido al panel"

    def get_app_list(self, request):
        # Reorganizar el orden de las aplicaciones
        app_list = super().get_app_list(request)
        # Ordenar las aplicaciones según tu preferencia
        app_list.sort(key=lambda x: x['name'])
        return app_list

# Registrar la clase personalizada
my_admin_site = MyAdminSite(name='myadmin')

# Registrar modelos en el sitio personalizado
#my_admin_site.register(MyModel)