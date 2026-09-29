# core/urls.py
from django.urls import path, include
from django.views.generic import RedirectView
from django.contrib import admin
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', RedirectView.as_view(url='/auth/login/', permanent=False), name='root_redirect'),  # Redirige a la ruta de login
    path('admin/', admin.site.urls),
    path('auth/', include('apps.authentication.urls')),                                         # Rutas de autenticación
    path('home/', include('apps.home.urls')),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),                                                   # Rutas del home
]
