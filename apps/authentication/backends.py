from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameBackend(ModelBackend):
    """Permite iniciar sesión con nombre de usuario o email (sin distinguir mayúsculas)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if not username or password is None:
            return None

        matches = list(
            User._default_manager.filter(
                Q(username__iexact=username) | Q(email__iexact=username)
            )[:2]
        )
        if len(matches) != 1:
            # Sin resultados o ambiguo: se ejecuta el hasher para igualar tiempos
            User().set_password(password)
            return None

        user = matches[0]
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
