# apps/home/urls.py
from django.urls import path, include
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import IsAuthenticated, IsAdminUser

# Vistas
from apps.home import views as v
from apps.home import views_dashboard as vd
from apps.home import views_verifactu as vv
from apps.home import views_factura as vf
from apps.home import views_email as ve

app_name = 'home'

# ----------------------------------------------------------------------
# 1. API REST (ViewSets) – con permisos
# ----------------------------------------------------------------------
router = DefaultRouter()
router.register(r'doctors', v.DoctorViewSet, basename='doctors')
router.register(r'docpercent', v.DocpercentViewSet, basename='docpercent')
router.register(r'centro', v.CentroViewSet, basename='centro')
router.register(r'especialidad', v.EspecialidadViewSet, basename='especialidad')
router.register(r'empresa', v.EmpresaViewSet, basename='empresa')
router.register(r'factura_r', v.Factura_RViewSet, basename='factura_r')
router.register(r'factura_c', v.Factura_CViewSet, basename='factura_c')
router.register(r'factura_d', v.Factura_DViewSet, basename='factura_d')
router.register(r'factura_v', v.Factura_VViewSet, basename='factura_v')
router.register(r'importes', v.ImportesViewSet, basename='importes')

# Aplicar permisos globales a todos los ViewSets
for route in router.urls:
    if hasattr(route.callback, 'cls'):
        route.callback.cls.permission_classes = [IsAuthenticated]

# ----------------------------------------------------------------------
# 2. Rutas de acción (protegidas)
# ----------------------------------------------------------------------
urlpatterns = [
    # API
    path('api/', include(router.urls)),

    # Docpercent detalle (mantiene ruta legacy)
    path(
        'api/docpercent/<str:spcode>/<str:especialidad>/<str:centro>/',
        login_required(v.DocpercentViewSet.as_view({
            'get': 'retrieve',
            'put': 'update',
            'patch': 'partial_update',
            'delete': 'destroy'
        })),
        name='docpercent-detail'
    ),

    # ------------------------------------------------------------------
    # Inicialización / Actualización
    # ------------------------------------------------------------------
    path(
        'init_factura/',
        login_required(staff_member_required(v.init_factura)),
        name='init_factura'
    ),

    # ------------------------------------------------------------------
    # Envío de facturas (POST + login)
    # ------------------------------------------------------------------
    path(
        'send/<str:factura_id>/',
        login_required(require_POST(ve.send_factura_consolidated)),
        name='send_factura'
    ),

    # ------------------------------------------------------------------
    # Exportación Veri*Factu – BATCH (POST JSON)
    # ------------------------------------------------------------------
    path('export2xml/', vv.export2xml, name='export2xml'),
    # ------------------------------------------------------------------
    # Logs (solo staff)
    # ------------------------------------------------------------------
    path('logs/view/', login_required(v.view_logs), name='view_logs'),
    path('logs/load/', login_required(v.load_log_json), name='load_log_json'),
    path('logs/download/', login_required(v.download_log_file), name='download_log_file'),
    path(
        'logs/clear/',
        staff_member_required(require_POST(v.clear_logs)),
        name='clear_logs'
    ),

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------
    path('configuracion/', login_required(v.config_paths), name='config_paths'),
    path('api/config/load/', login_required(v.config_load), name='config_load'),
    path('api/config/save/', login_required(require_POST(v.config_save)), name='config_save'),

    # ------------------------------------------------------------------
    # Autenticación
    # ------------------------------------------------------------------
    path('register/', v.register, name='register'),

    # ------------------------------------------------------------------
    # Listados UI
    # ------------------------------------------------------------------
    path('doctor/', login_required(v.doctor_list), name='doctor_list'),
    path('docpercent/', login_required(v.docpercent_list), name='docpercent_list'),
    path('centro/', login_required(v.centro_list), name='centro_list'),
    path('empresa/', login_required(v.empresa_list), name='empresa_list'),
    path('especialidad/', login_required(v.especialidad_list), name='especialidad_list'),
    path('importes/', login_required(v.importes_list), name='importes_list'),
    path('factura_r/', login_required(v.factura_r_list), name='factura_r_list'),
    path('factura_c/', login_required(v.factura_c_list), name='factura_c_list'),
    path('factura_d/', login_required(v.factura_d_list), name='factura_d_list'),
    path('factura_v/', login_required(v.factura_v_list), name='factura_v_list'),

    # ------------------------------------------------------------------
    # Impresión / PDF
    # ------------------------------------------------------------------
    path('factura_ou/<str:pk>/', login_required(v.factura_ou_prn), name='factura_ou_prn'),

    # ------------------------------------------------------------------
    # Actualizaciones masivas (solo staff)
    # ------------------------------------------------------------------
    path('upd_sociedad/', staff_member_required(require_POST(v.updSociedad)), name='upd_sociedad'),
    path('upd_especialidad/', staff_member_required(require_POST(v.updEspecialidad)), name='upd_especialidad'),
    path('upd_importes/', staff_member_required(require_POST(v.updImportes)), name='upd_importes'),
    
    path('upd_factura_r/', v.updFactura_R, name='upd_factura_r'),
    path('upd_factura_c/', v.updFactura_C, name='upd_factura_c'),
    
    # --- Veri*Factu: Validaciones ---
    path("validate/<str:facturaId>/", vv.validateFactura, name="validate_factura"),
    path("validate_qr/<str:facturaId>/", vv.validateQRCode, name="validate_qr"),

    # Opcionalmente, si también expones export2xml:
    path("export_xml/", vv.export2xml, name="export_xml"),
   
    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    path('dashboard/', login_required(vd.dashboard), name='dashboard'),
]

# ----------------------------------------------------------------------
# Rutas DEPRECATED (mantener solo si se migran)
# ----------------------------------------------------------------------
"""
# path('validate/<str:factura_id>/', vv.validate_factura, name='validate_factura'),
# path('validate_qr/<str:factura_id>/', vv.validate_qr_code, name='validate_qr_code'),
# path('xml_sii/<str:factura_id>/', vv.generate_xml_sii, name='generate_xml_sii'),
# path('export_xml_batch/', vv.export_xml_batch, name='export_xml_batch'),
"""