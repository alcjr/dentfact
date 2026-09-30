import json
from django.apps import apps

data = json.load(open('data.json', encoding='utf-8'))
cambiados = {}
for obj in data:
    model = apps.get_model(obj['model'])
    for f in model._meta.concrete_fields:
        if (f.get_internal_type() in ('CharField', 'TextField')
                and not f.null and f.name in obj['fields']
                and obj['fields'][f.name] is None):
            obj['fields'][f.name] = ''
            k = (obj['model'], f.name)
            cambiados[k] = cambiados.get(k, 0) + 1
json.dump(data, open('data_clean.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=2)
for k, n in sorted(cambiados.items()):
    print(n, k)
print('Total campos corregidos:', sum(cambiados.values()))