import json, collections
from django.apps import apps

data = json.load(open('data.json', encoding='utf-8'))
problemas = collections.Counter()

for obj in data:
    model = apps.get_model(obj['model'])
    for f in model._meta.concrete_fields:
        if f.primary_key or f.name not in obj['fields']:
            continue
        v = obj['fields'][f.name]
        if v is None and not f.null:
            problemas[(obj['model'], f.name, 'NULL en campo NOT NULL')] += 1
        if isinstance(v, str) and getattr(f, 'max_length', None) and len(v) > f.max_length:
            problemas[(obj['model'], f.name, 'supera max_length')] += 1

for k, n in sorted(problemas.items()):
    print(n, k)