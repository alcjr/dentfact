from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from .forms import LoginForm, SignUpForm
from django.contrib import messages

def login_view(request):
    form = LoginForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            username = form.cleaned_data.get("username")
            password = form.cleaned_data.get("password")
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                # Obtén la URL de redirección
                next_page = request.GET.get('next', 'home:dashboard')
                return redirect(next_page)  # Redirige a la página deseada
            else:
                messages.error(request, "Credenciales no válidas.")
        else:
            messages.error(request, "Error al validar el formulario.")
    return render(request, "login.html", {"form": form})

def register_user(request):
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()  # Establece la contraseña y actualiza el perfil
            login(request, user)  # Inicia sesión automáticamente
            messages.success(request, "Registro completado con éxito. Bienvenido/a!")
            return redirect("home:dashboard")
        else:
            # Los errores del formulario se mostrarán en la plantilla
            pass
    else:
        form = SignUpForm()
    return render(request, "register.html", {"form": form})

def logout_view(request):
    logout(request)
    messages.success(request, "Has cerrado sesión exitosamente.")
    return redirect('authentication:login') 