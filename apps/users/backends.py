from django.contrib.auth.backends import BaseBackend

from .models import User


class AbiturientIDBackend(BaseBackend):
    def authenticate(self, request, abiturient_id=None, **kwargs):
        if abiturient_id is None:
            return None
        abiturient_id = abiturient_id.strip()
        try:
            user = User.objects.get(abiturient_id=abiturient_id)
        except User.DoesNotExist:
            return None
        if not user.is_verified or not user.is_active:
            return None
        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
