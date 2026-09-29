from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Profile

class LoginForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'placeholder': 'Username'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': 'Password'}))

class SignUpForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'placeholder': 'Username'}))
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'placeholder': 'Email'}))
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': 'Password'}))
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': 'Confirm Password'}))

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username")
        email = cleaned_data.get("email")
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        # Validar que las contraseñas coincidan
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Las contraseñas no coinciden.")

        # Validar que el usuario exista y esté pre-registrado
        try:
            user = User.objects.get(username=username, email=email)
            if not hasattr(user, 'profile') or not user.profile.is_pre_registered:
                raise forms.ValidationError("Este usuario no está autorizado para registrarse. Contacta al administrador.")
            if user.has_usable_password():
                raise forms.ValidationError("Este usuario ya tiene una contraseña establecida. Usa 'Recuperar Contraseña' si la olvidaste.")
        except User.DoesNotExist:
            raise forms.ValidationError("No existe un usuario con este username y email.")

        return cleaned_data

    def save(self):
        username = self.cleaned_data["username"]
        email = self.cleaned_data["email"]
        password = self.cleaned_data["password1"]
        user = User.objects.get(username=username, email=email)
        user.set_password(password)  # Establece la contraseña
        user.profile.is_pre_registered = False  # Marca como registrado
        user.save()
        user.profile.save()
        return user