from django import forms
from .models import Factura_R, Factura_C, Factura_D, Doctor, Importes, Docpercent, Centro, Especialidad, Sociedad


class FacturaForm_R(forms.ModelForm):
    class Meta:
        model = Factura_R
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        decimal_fields = ['SUB_TOTAL', 'TOTAL']
        for field in decimal_fields:    
            value = cleaned_data.get(field)
            if value in [None, '']:
                cleaned_data[field] = 0.0  # Establece un valor predeterminado
        return cleaned_data


class FacturaForm_D(forms.ModelForm):
    class Meta:
        model = Factura_D
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        decimal_fields = ['BRUTO_TOTAL', 'GASTOS', 'IRPF', 'BASE_IMP', 'BASE_CAL', 'TOTAL']
        for field in decimal_fields:
            value = cleaned_data.get(field)
            if value in [None, '']:
                cleaned_data[field] = 0.0  # Establece un valor predeterminado
        return cleaned_data

class FacturaForm_C(forms.ModelForm):
    class Meta:
        model = Factura_C
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        decimal_fields = ['BRUTO', 'NETO', 'PORCENTAJE']
        for field in decimal_fields:
            value = cleaned_data.get(field)
            if value in [None, '']:
                cleaned_data[field] = 0.0  # Establece un valor predeterminado
        return cleaned_data

class DoctorForm(forms.ModelForm):
    class Meta:
        model = Doctor
        fields = '__all__'
        widgets = {
            'SPCODE': forms.TextInput(attrs={'readonly': True}),
            'DOCTOR': forms.TextInput(attrs={'class': 'form-control', 'readonly': True}),  # Solo lectura
            'COLEGIADO': forms.TextInput(attrs={'class': 'form-control'}),          
            'I_APELLIDO': forms.TextInput(attrs={'class': 'form-control'}),
            'II_APELLIDO': forms.TextInput(attrs={'class': 'form-control'}),
            'NOMBRE': forms.TextInput(attrs={'class': 'form-control'}),
            'DNI': forms.TextInput(attrs={'class': 'form-control'}),
            'SOCIEDAD': forms.TextInput(attrs={'class': 'form-control'}),
            'GASTOS': forms.TextInput(attrs={'class': 'form-control'}),
            'EMAIL': forms.EmailInput(attrs={'class': 'form-control'}),
            'DIRECCION': forms.TextInput(attrs={'class': 'form-control'}),
            'CIUDAD': forms.TextInput(attrs={'class': 'form-control'}),
            'POSTAL': forms.TextInput(attrs={'class': 'form-control'}),
            'TELEFONO': forms.TextInput(attrs={'class': 'form-control'}),
            'CUENTA': forms.TextInput(attrs={'class': 'form-control'}), 
            'GABINETE_01': forms.TextInput(attrs={'class': 'form-control'}),
            'GABINETE_02': forms.TextInput(attrs={'class': 'form-control'}),         
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.required = False  # Establece que los campos no son obligatorios

    def clean(self):
        cleaned_data = super().clean()
        nombre = cleaned_data.get('NOMBRE', '')
        i_apellido = cleaned_data.get('I_APELLIDO', '')
        ii_apellido = cleaned_data.get('II_APELLIDO', '')
        
        # Concatenar los campos para el campo DOCTOR
        doctor_value = f"{nombre} {i_apellido} {ii_apellido}".strip()
        
        # Establecer el valor del campo DOCTOR
        cleaned_data['DOCTOR'] = doctor_value
        
        return cleaned_data

class ImportesForm(forms.ModelForm):
    class Meta:
        model = Importes
        fields = '__all__'


class DocpercentForm(forms.ModelForm):
    class Meta:
        model = Docpercent
        fields = '__all__'

class CentroForm(forms.ModelForm):
    class Meta:
        model = Centro
        fields = '__all__'

class EspecialidadForm(forms.ModelForm):
    class Meta:
        model = Especialidad
        fields = '__all__'

class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Sociedad
        fields = '__all__'
