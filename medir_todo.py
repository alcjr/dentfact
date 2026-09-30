import json
from django.apps import apps

data = json.load(open('data_clean.json', encoding='utf-8'))
maximos = {}
for o in data:
    m = apps.get_model(o['model'])
    for f in m._meta.concrete_fields:
        ml = getattr(f, 'max_length', None)
        v = o['fields'].get(f.name)
        if ml and isinstance(v, str):
            k = (o['model'], f.name, ml)
            maximos[k] = max(maximos.get(k, 0), len(v))

for (modelo, campo, ml), real in sorted(maximos.items()):
    if real > ml:
        print(f"{modelo}.{campo}: max_length={ml} | máximo real={real}")
print("Revisión completa")