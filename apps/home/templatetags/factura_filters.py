from django import template

register = template.Library()

@register.filter
def replace(value, arg):
    """
    Reemplaza todas las ocurrencias de una subcadena en el valor con otra subcadena.
    Uso: {{ value | replace:"viejo:nuevo" }}
    Ejemplo: {{ "725.79" | replace:".:," }} produce "725,79"
    """
    try:
        old, new = arg.split(':')
        return str(value).replace(old, new)
    except (ValueError, TypeError):
        return value