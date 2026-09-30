import json
from django.apps import apps

data = json.load(open('data.json', encoding='utf-8'))

# 1) Longitud máxima real frente al límite actual (solo imprime números)
Modelo = apps.get_model('home.factura_d')
for campo in ('DOCTOR', 'POSTAL'):
    actual = Modelo._meta.get_field(campo).max_length
    valores = [o['fields'].get(campo) or '' for o in data if o['model'] == 'home.factura_d']
    mx = max(len(v) for v in valores)
    largas = sum(1 for v in valores if len(v) > actual)
    print(f"{campo}: max_length actual={actual} | máximo real={mx} | filas que exceden={largas}")

# 2) Centro con N_CENTRO nulo (imprime solo la clave, sin datos personales)
for o in data:
    if o['model'] == 'home.centro' and o['fields'].get('N_CENTRO') is None:
        print("Centro con N_CENTRO nulo -> pk:", o['pk'])