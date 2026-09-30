from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from .forms import LoginForm, SignUpForm

DEFAULT_REDIRECT = "home:dashboard"
REMEMBER_ME_SECONDS = 60 * 60 * 24 * 14  # 14 días


def _get_safe_next(request):
    """Devuelve el 'next' solo si apunta a este mismo host (evita open redirect)."""
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return ""


@sensitive_post_parameters("password")
@never_cache
def login_view(request):
    next_url = _get_safe_next(request)

    if request.user.is_authenticated:
        return redirect(next_url or DEFAULT_REDIRECT)

    form = LoginForm(request.POST or None)

    if request.method == "POST":
        if form.is_valid():
            user = authenticate(
                request,
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password"],
            )
            if user is not None:
                login(request, user)
                # Sesión de navegador (0) o persistente (14 días)
                if request.POST.get("remember_me"):
                    request.session.set_expiry(REMEMBER_ME_SECONDS)
                else:
                    request.session.set_expiry(0)
                return redirect(next_url or DEFAULT_REDIRECT)
            messages.error(request, "Usuario o contraseña incorrectos.")
        else:
            messages.error(request, "Introduce tu usuario y tu contraseña.")

    return render(request, "login.html", {"form": form, "next": next_url})


def register_user(request):
    if request.user.is_authenticated:
        return redirect(DEFAULT_REDIRECT)

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Necesario si hay varios AUTHENTICATION_BACKENDS
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, "Cuenta activada. ¡Bienvenido/a!")
            return redirect(DEFAULT_REDIRECT)
    else:
        form = SignUpForm()
    return render(request, "register.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, "Has cerrado sesión correctamente.")
    return redirect("authentication:login")
