from django.db import models
from django.contrib.auth.models import User

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    is_pre_registered = models.BooleanField(default=True)

    def __str__(self):
        return f"Profile for {self.user.username}"