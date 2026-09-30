from django.db import models
from django.core.exceptions import ValidationError
import uuid
from django.db import models
from decimal import Decimal, InvalidOperation
from rest_framework import serializers
from django.db import models
from django.core.exceptions import ValidationError
import re


class Importes(models.Model):
    # Definición de los campos
    id = models.AutoField(primary_key=True)                                 # ID autoincremental
    SPCODE = models.CharField(max_length=10)                                # Código SPCODE, ajusta el tamaño si es necesario
    CENTRO = models.CharField(max_length=4)                                 # Centro, ajusta el tamaño según tus necesidades
    N_CENTRO = models.CharField(max_length=100, blank=True, null=True)      # Nombre del centro
    ESPECIALIDAD = models.CharField(max_length=100)                         # Especialidad del doctor
    DOCTOR = models.CharField(max_length=100, blank=True, null=True)        # Nombre del doctor
    COLABORADOR = models.CharField(max_length=100, blank=True, null=True)   # Colaborador
    COLEGIADO = models.CharField(max_length=10, blank=True, null=True)     # Colegiado
    CIF = models.CharField(max_length=15, blank=True, null=True)            # CIF, ajusta el tamaño según formato
    LIQUIDACION = models.CharField(max_length=20, blank=True, null=True)    # Liquidación
    L_DESDE = models.CharField(max_length=10, blank=True, null=True)        # Desde fecha
    L_HASTA = models.CharField(max_length=10, blank=True, null=True)        # Hasta fecha
  
    # Campos de tipo REAL en la tabla original
    PP_BASE = models.CharField(max_length=10, blank=True, null=True)
    PP_LIQUIDO = models.CharField(max_length=10, blank=True, null=True)
    PM_BASE = models.CharField(max_length=10, blank=True, null=True)
    PM_LIQUIDO = models.CharField(max_length=10, blank=True, null=True)
    P_BASE = models.CharField(max_length=10, blank=True, null=True)
    P_LIQUIDO = models.CharField(max_length=10, blank=True, null=True)
    R_BASE = models.CharField(max_length=10, blank=True, null=True)
    R_LIQUIDO = models.CharField(max_length=10, blank=True, null=True)
    C_FIJA = models.CharField(max_length=10, blank=True, null=True)
    C_TURNO = models.CharField(max_length=10, blank=True, null=True)
    PPA_BASE = models.CharField(max_length=10, blank=True, null=True)
    PPA_LIQUIDO = models.CharField(max_length=10, blank=True, null=True)
    PMA_BASE = models.CharField(max_length=10, blank=True, null=True)
    PMA_LIQUIDO = models.CharField(max_length=10, blank=True, null=True)
    PA_BASE = models.CharField(max_length=10, blank=True, null=True)
    PA_LIQUIDO = models.CharField(max_length=10, blank=True, null=True)
    HHRR = models.CharField(max_length=10, blank=True, null=True)
    BRUTO = models.CharField(max_length=10, blank=True, null=True)
    NETO = models.CharField(max_length=10, blank=True, null=True)
        
    # Definir la clave primaria compuesta
    class Meta:
        db_table = 'dentfact_importes'
       # unique_together = (('L_HASTA', 'SPCODE', 'CENTRO', 'ESPECIALIDAD'),)


# Modelo para las facturas recibidas
class Factura_R(models.Model):
    FACTURA = models.CharField(max_length=255, primary_key=True)
    FECHA = models.CharField(max_length=255)
    PERIODO = models.CharField(max_length=255)
    CIF = models.CharField(max_length=255)
    DESCRIPCION_SOC = models.CharField(max_length=255)
    DIRECCION_SOC = models.CharField(max_length=255)
    POSTAL_SOC = models.CharField(max_length=255)
    CENTRO = models.CharField(max_length=255)
    CENTRO_N = models.CharField(max_length=255)
    SUBTOTAL = models.CharField(max_length=255)
    TOTAL = models.CharField(max_length=255)
    

    class Meta:
        db_table = 'dentfact_factura_r'

    def __str__(self):
        return self.FACTURA


class Factura_C(models.Model):
    FACTURA = models.CharField(primary_key=True, max_length=255, default='Factura_default')
    L_DESDE = models.CharField(max_length=255, default='Fecha desconocida')  # Valor por defecto
    L_HASTA = models.CharField(max_length=255, default='Fecha desconocida')  # Valor por defecto
    SPCODE = models.CharField(max_length=255, default='SPCODE desconocido')  # Valor por defecto
    DOCTOR = models.CharField(max_length=255, default='Doctor desconocido')  # Valor por defecto
    ESPECIALIDAD = models.CharField(max_length=255, default='Especialidad desconocida')  # Valor por defecto
    COLABORADOR = models.CharField(max_length=255, default='Colaborador desconocido')  # Valor por defecto
    COLEGIADO = models.CharField(max_length=255, default='Colegiado desconocido')  # Valor por defecto
    I_APELLIDO = models.CharField(max_length=255, default='I_APELLIDO desconocido')  # Valor por defecto
    II_APELLIDO = models.CharField(max_length=255, default='II_APELLIDO desconocido')  # Valor por defecto
    NOMBRE = models.CharField(max_length=255, default='NOMBRE desconocido')  # Valor por defecto
    DNI = models.CharField(max_length=255, default='DNI desconocido')  # Valor por defecto
    ESTADO = models.CharField(max_length=255, default='Estado desconocido')  # Valor por defecto
    EMAIL = models.CharField(max_length=255, default='E-mail desconocido')  # Valor por defecto
    DIRECCION = models.CharField(max_length=255, default='Dirección desconocida')  # Valor por defecto 
    CIUDAD = models.CharField(max_length=255, default='Ciudad desconocida')  # Valor por defecto
    POSTAL = models.CharField(max_length=255, default='Postal desconocida')  # Valor por defecto
    TELEFONO = models.CharField(max_length=255, default='Teléfono desconocido')  # Valor por defecto
    CUENTA = models.CharField(max_length=255, default='Cuenta desconocida')  # Valor por defecto
    CENTRO = models.CharField(max_length=255, default='Centro desconocido')  # Valor por defecto
    N_CENTRO = models.CharField(max_length=255, default='N_CENTRO desconocido')  # Valor por defecto
    SOCIEDAD = models.CharField(max_length=255, default='Sociedad desconocida')  # Valor por defecto
    CIF = models.CharField(max_length=255, default='CIF desconocida')  # Valor por defecto
    DESCRIPCION_SOC = models.CharField(max_length=255, default='Descripción desconocida')  # Valor por defecto
    DIRECCION_SOC = models.CharField(max_length=255, default='Dirección desconocida')  # Valor por defecto
    POSTAL_SOC = models.CharField(max_length=255, default='Postal desconocida')  # Valor por defecto
    PROVINCIA_SOC = models.CharField(max_length=255, default='Provincia desconocida')  # Valor por defecto
    REPRESENTANTE = models.CharField(max_length=255, default='Representante desconocida')  # Valor por defecto
    NIF_REP = models.CharField(max_length=255, default='NIF desconocida')  # Valor por defecto
    LIQUIDACION = models.CharField(max_length=255, default='Liquidación desconocida')  # Valor por defecto
    HHRR = models.CharField(max_length=255, default='HHRR desconocida')  # Valor por defecto
    NETO = models.CharField(max_length=255, default='0')  # Valor por defecto
    BRUTO = models.CharField(max_length=255, default='0')  # Valor por defecto
    PORCENTAJE = models.CharField(max_length=255, default='0')  # Valor por defecto
    GASTOS = models.CharField(max_length=255, default='0')  # Valor por defecto
    IRPF = models.CharField(max_length=255, default='0')  # Valor por defecto
    CALCULO = models.CharField(max_length=255, default='Cálculo')  # Valor por defecto
   
    class Meta:
        db_table = 'dentfact_factura_c'
        verbose_name = 'Factura_C'

class Factura_D(models.Model):
    
    FACTURA = models.CharField(max_length=255, primary_key=True)
    MES = models.CharField(max_length=2, null=True, blank=True)
    ANNO = models.CharField(max_length=4, null=True, blank=True)
    EMISION = models.CharField(max_length=10, null=True, blank=True)
    SPCODE = models.CharField(max_length=6, null=True, blank=True)
    DOCTOR = models.CharField(max_length=255, null=True, blank=True)
    DNI = models.CharField(max_length=255, null=True, blank=True)
    COLEGIADO = models.CharField(max_length=255, null=True, blank=True)
    COLABORADOR = models.CharField(max_length=255, null=True, blank=True)
    EMAIL = models.CharField(max_length=255, null=True, blank=True)
    TELEFONO = models.CharField(max_length=255, null=True, blank=True)
    DIRECCION = models.CharField(max_length=255, null=True, blank=True)
    CUENTA = models.CharField(max_length=255, null=True, blank=True)
    ESTADO = models.CharField(max_length=255, null=True, blank=True)
    CIF = models.CharField(max_length=255, null=True, blank=True)
    SOCIEDAD = models.CharField(max_length=255, null=True, blank=True)
    DESCRIPCION_SOC = models.CharField(max_length=255, null=True, blank=True)
    DIRECCION_SOC = models.CharField(max_length=255, null=True, blank=True)
    POSTAL_SOC = models.CharField(max_length=20, null=True, blank=True)
    CIUDAD = models.CharField(max_length=255, null=True, blank=True)
    REPRESENTANTE = models.CharField(max_length=255, null=True, blank=True)
    NIF_REP = models.CharField(max_length=255, null=True, blank=True)
    GASTOS = models.CharField(max_length=255, null=True, blank=True)
    IRPF = models.CharField(max_length=255, null=True, blank=True)
    CUOTA_IRPF = models.CharField(max_length=255, null=True, blank=True)  # Corregido "CUOTA_IRVARCHAR" a "CUOTA_IRPF"
    TOTAL_FACTURA = models.CharField(max_length=255, null=True, blank=True)
    BASE_FACTURA = models.CharField(max_length=255, null=True, blank=True)
    BRUTO_TOTAL = models.CharField(max_length=255, null=True, blank=True)
    CALCULO = models.CharField(max_length=255, null=True, blank=True)
    PORCENTAJE = models.CharField(max_length=255, null=True, blank=True)
    CALCULO_TOTAL = models.CharField(max_length=255, null=True, blank=True)
    L_DESDE = models.CharField(max_length=10, null=True, blank=True)
    L_HASTA = models.CharField(max_length=10, null=True, blank=True)
    I_APELLIDO = models.CharField(max_length=255, null=True, blank=True)
    II_APELLIDO = models.CharField(max_length=255, null=True, blank=True)
    NOMBRE = models.CharField(max_length=255, null=True, blank=True)
    ESPECIALIDAD = models.CharField(max_length=255, null=True, blank=True)
    CODIGO = models.CharField(max_length=255, null=True, blank=True)
    POSTAL = models.CharField(max_length=20, null=True, blank=True)
    PROVINCIA_SOC = models.CharField(max_length=255, null=True, blank=True)
    LIQUIDACION = models.CharField(max_length=255, null=True, blank=True)
    HHRR = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'dentfact_factura_d'  # Nombre exacto de la tabla en la base de datos
        #managed = False

    def __str__(self):
        return self.FACTURA

# =============================================================================
# 4. FACTURA_V - ¡CORREGIDO! Unique en 'factura' + índice compuesto
# =============================================================================
class Factura_V(models.Model):
    id = models.AutoField(primary_key=True)
    factura = models.ForeignKey(
        Factura_D,
        on_delete=models.CASCADE,
        to_field='FACTURA',
        db_column='factura',
        related_name='verifactu_entries',
        db_constraint=False,  # Evita FK si hay problemas de integridad temporal
    )

    qr_code = models.TextField(default='', blank=True)
    qr_base64 = models.TextField(blank=True, null=True)
    hash = models.CharField(max_length=64, default='')
    previous_hash = models.CharField(max_length=64, default='')
    sif_id = models.CharField(max_length=50, blank=True, null=True)  # Ya no unique
    xml = models.TextField(default='', blank=True)

    class Meta:
        db_table = 'dentfact_factura_v'
        unique_together = ('factura',)  # ¡CLAVE PARA bulk_create!
        indexes = [
            models.Index(fields=['factura']),
            models.Index(fields=['sif_id']),
            models.Index(fields=['hash']),
        ]

    def clean(self):
        pattern = r'^[0-9a-fA-F]{64}$'
        if self.hash and not re.match(pattern, self.hash):
            raise ValidationError({'hash': 'Hash inválido (64 hex)'})
        if self.previous_hash and not re.match(pattern, self.previous_hash):
            raise ValidationError({'previous_hash': 'Hash anterior inválido'})

    def __str__(self):
        return f"VeriFactu {self.factura.FACTURA}"


class Doctor(models.Model):
    SPCODE = models.CharField(max_length=255, primary_key=True)
    COLEGIADO = models.CharField(max_length=50, null=True, blank=True)
    DOCTOR = models.CharField(max_length=255, null=True, blank=True)
    I_APELLIDO = models.CharField(max_length=255, null=True, blank=True)
    II_APELLIDO = models.CharField(max_length=255, null=True, blank=True)
    NOMBRE = models.CharField(max_length=255, null=True, blank=True)
    DNI = models.CharField(max_length=50, null=True, blank=True)
    CIF = models.CharField(max_length=255, null=True, blank=True)
    GASTOS = models.CharField(max_length=5, null=True, blank=True)
    ESTADO = models.CharField(max_length=255, null=True, blank=True)
    EMAIL = models.EmailField(max_length=254, null=True, blank=True)
    DIRECCION = models.TextField(null=True, blank=True)
    CIUDAD = models.CharField(max_length=255, null=True, blank=True)
    POSTAL = models.CharField(max_length=20, null=True, blank=True)
    TELEFONO = models.CharField(max_length=50, null=True, blank=True)
    CUENTA = models.CharField(max_length=255, null=True, blank=True)
    CODIGO = models.CharField(max_length=255, null=True, blank=True)
    ESPECIALIDAD = models.CharField(max_length=255, null=True, blank=True)
    COLABORADOR = models.CharField(max_length=255, null=True, blank=True)
    GABINETE_01 = models.CharField(max_length=5, null=True, blank=True)
    GABINETE_02 = models.CharField(max_length=5, null=True, blank=True)
    
    class Meta:
        db_table = 'dentfact_doctor'

    def __str__(self):
        return f"{self.DOCTOR} ({self.SPCODE})"

from decimal import Decimal, InvalidOperation

class Docpercent(models.Model):
    id = models.AutoField(primary_key=True)
    SPCODE = models.ForeignKey(Doctor, on_delete=models.CASCADE)
    ESPECIALIDAD = models.TextField(verbose_name="Especialidad")
    CENTRO = models.TextField(verbose_name="Centro")
    IRPF = models.DecimalField(max_digits=4, decimal_places=2, verbose_name="IRPF", null=True, blank=True)
    PORCENTAJE = models.DecimalField(max_digits=4, decimal_places=2, verbose_name="PORCENTAJE", null=True, blank=True)

    class Meta:
        db_table = 'dentfact_docpercent'
        verbose_name = 'Docpercent'
        unique_together = (('SPCODE', 'ESPECIALIDAD', 'CENTRO'))
        constraints = [
            models.UniqueConstraint(fields=['SPCODE', 'ESPECIALIDAD', 'CENTRO'], name='unique_spcode_especialidad_centro')
        ]

    def clean(self):
        """Limpia los valores no numéricos de IRPF y PORCENTAJE antes de validar o guardar."""
        for field in ['IRPF', 'PORCENTAJE']:
            value = getattr(self, field)
            if value in [None, '', ' ', '-', 'NULL']:
                setattr(self, field, Decimal('0.00'))
            else:
                try:
                    setattr(self, field, Decimal(str(value)))
                except (InvalidOperation, ValueError, TypeError):
                    setattr(self, field, Decimal('0.00'))

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.SPCODE} - {self.ESPECIALIDAD} - {self.CENTRO}"



class Sociedad(models.Model):
    ID_SOC = models.AutoField(primary_key=True)
    CIF = models.TextField(default="", verbose_name="CIF")
    SOCIEDAD = models.TextField(default="", verbose_name="Nombre")
    DESCRIPCION_SOC = models.TextField(default="", verbose_name="Descripción")
    DIRECCION_SOC = models.TextField(verbose_name="Dirección de la Sociedad")
    POSTAL_SOC = models.TextField(verbose_name="Código Postal de la Sociedad")
    PROVINCIA_SOC = models.TextField(verbose_name="Provincia de la Sociedad")
    REPRESENTANTE = models.TextField(verbose_name="Representante de la Sociedad")
    NIF_REP = models.TextField(verbose_name="NIF del Representante")

    class Meta:
        db_table = 'dentfact_sociedad'  
        verbose_name = 'Sociedad'

    def __str__(self):
        return f"({self.CIF})"

class Centro(models.Model):
    CENTRO = models.TextField(primary_key=True, max_length=4, verbose_name="Código")
    N_CENTRO = models.TextField(verbose_name="Nombre")
    DIRECCION = models.TextField(verbose_name="Dirección")
    POBLACION = models.TextField(verbose_name="Población")
    PROVINCIA = models.TextField(verbose_name="Provincia")
    POSTAL = models.TextField(verbose_name="Postal")
    EMAIL = models.EmailField(default="", verbose_name="Email")
    WWW = models.TextField(verbose_name="WWW")
    
    class Meta:
        db_table = 'dentfact_centro'  
        verbose_name = 'Centro'

    def __str__(self):
        return f"({self.CENTRO})"
    
class Especialidad(models.Model):
    ESPECIALIDAD = models.TextField(primary_key=True, verbose_name="Especialidad")
    DESCRIPCION = models.TextField(null=True, blank=True)  # Permitir valores nulos
   
    class Meta:
        db_table = 'dentfact_especialidad'  
        verbose_name = 'Especialidad'

    def __str__(self):
        return f"({self.ESPECIALIDAD})"
    
