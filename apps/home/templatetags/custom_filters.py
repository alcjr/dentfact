from django import template
import locale

register = template.Library()

@register.filter
def format_currency(value):
    try:
        # Asegurarse de que value es un número
        float_value = float(value)
        locale.setlocale(locale.LC_ALL, 'es_ES.UTF-8')
        return locale.currency(float_value, grouping=True, symbol='€', international=False)
    except ValueError:
        # Manejo de error si el valor no puede ser convertido a float
        return value  # o puedes devolver un mensaje de error
    
@register.filter
def get_item(dictionary, key):
    """
    Obtiene un ítem de un diccionario o una lista usando una clave o índice.
    
    :param dictionary: El diccionario o lista de la cual se quiere obtener el ítem.
    :param key: La clave o índice del ítem a obtener.
    :return: El valor del ítem correspondiente o None si no existe.
    """
    if isinstance(dictionary, dict):
        return dictionary.get(key, None)
    elif hasattr(dictionary, '__getitem__'):  # Esto maneja listas, tuplas, etc.
        try:
            return dictionary[key]
        except (IndexError, KeyError, TypeError):
            return None
    else:
        return None

register = template.Library()

@register.filter(name='convertToFloat')
def convert_to_float(value):
    try:
        return float(value)
    except ValueError:
        return value  # or return 0, or handle as needed
    
@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

register = template.Library()

@register.filter
def to_float(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0  # Valor por defecto si la conversión falla