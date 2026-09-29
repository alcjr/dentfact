from rest_framework import serializers
from .models import Doctor, Docpercent, Centro, Sociedad, Especialidad, Importes, Factura_R, Factura_D, Factura_C, Factura_V
from django.shortcuts import get_object_or_404
from decimal import Decimal, InvalidOperation

class DoctorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Doctor
        fields = [
            'SPCODE', 'COLEGIADO', 'DOCTOR', 'I_APELLIDO', 
            'II_APELLIDO', 'NOMBRE', 'DNI', 'CIF', 'GASTOS',
            'ESTADO', 'EMAIL', 'DIRECCION', 'CIUDAD', 'POSTAL',
            'TELEFONO', 'CUENTA'
        ]
        extra_kwargs = {
            'SPCODE': {'required': False},
            'EMAIL': {'allow_blank': True},  # Permitir cadenas vacías
        }

    def validate(self, data):
        if 'DOCTOR' in data:
            nombre = data.get('NOMBRE', self.instance.NOMBRE if self.instance else None)
            i_apellido = data.get('I_APELLIDO', self.instance.I_APELLIDO if self.instance else None)
            ii_apellido = data.get('II_APELLIDO', self.instance.II_APELLIDO if self.instance else None)
            expected_doctor = f"{i_apellido or ''} {ii_apellido or ''} {nombre or ''}".strip().replace("  ", " ")
            if data['DOCTOR'] != expected_doctor:
                data['NOMBRE'] = nombre
                data['I_APELLIDO'] = i_apellido
                data['II_APELLIDO'] = ii_apellido
        return data

# serializers.py
from rest_framework import serializers
from .models import Docpercent, Doctor
from decimal import Decimal


class SafeDecimalField(serializers.DecimalField):
    def to_representation(self, value):
        # Si value no es convertible a Decimal, devolver 0.0
        try:
            return Decimal(value)
        except (TypeError, ValueError, InvalidOperation):
            return Decimal('0.0')

class DocpercentSerializer(serializers.ModelSerializer):
    PORCENTAJE = SafeDecimalField(max_digits=5, decimal_places=2, coerce_to_string=False)
    IRPF = SafeDecimalField(max_digits=5, decimal_places=2, coerce_to_string=False)

    class Meta:
        model = Docpercent
        fields = '__all__'

class EmpresaSerializer(serializers.ModelSerializer):
    # Hacer los campos opcionales
    DIRECCION_SOC = serializers.CharField(required=False, allow_blank=True)
    PROVINCIA_SOC = serializers.CharField(required=False, allow_blank=True)
    REPRESENTANTE = serializers.CharField(required=False, allow_blank=True)
    NIF_REP = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Sociedad
        fields = ['ID_SOC', 'SOCIEDAD', 'DESCRIPCION_SOC', 'DIRECCION_SOC', 'POSTAL_SOC', 'PROVINCIA_SOC', 'CIF', 'REPRESENTANTE', 'NIF_REP']
        read_only_fields = ['ID_SOC']

class CentroSerializer(serializers.ModelSerializer):
    class Meta:
        model = Centro
        fields = [ 
            'CENTRO', 'N_CENTRO', 'DIRECCION', 'POBLACION', 
            'PROVINCIA', 'POSTAL', 'EMAIL', 'WWW' 
        ]
        extra_kwargs = {
            'CENTRO': {'required': False},
            'N_CENTRO': {'required': False},
            'DIRECCION': {'required': False},
            'POBLACION': {'required': False},
            'PROVINCIA': {'required': False},
            'POSTAL': {'required': False},
            'WWW': {'required': False}
        }

class EspecialidadSerializer(serializers.ModelSerializer):
    DESCRIPCION = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Especialidad
        fields = ['ESPECIALIDAD', 'DESCRIPCION']
        read_only_fields = ['ESPECIALIDAD']  # ESPECIALIDAD no debe modificarse en una actualización

class ImportesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Importes
        fields = '__all__'

class Factura_RSerializer(serializers.ModelSerializer):
    class Meta:
        model = Factura_R
        fields = '__all__'

class Factura_CSerializer(serializers.ModelSerializer):
    class Meta:
        model = Factura_C
        fields = '__all__'


class Factura_DSerializer(serializers.ModelSerializer):
    class Meta:
        model = Factura_D
        fields = '__all__'
        
        
class Factura_VSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Factura_V
        fields = ['id', 'factura', 'hash', 'previous_hash', 'sif_id', 'qr_code', 'qr_base64']
