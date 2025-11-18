"""

"""

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils import timezone
from django.conf import settings


class TokenGenerator(PasswordResetTokenGenerator):

    @property
    def timeout(self):
        return getattr(settings, "PASSWORD_RESET_TIMEOUT", 3600)

    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{user.password}{user.last_login or ''}{timestamp}"

    def check_token(self, user, token):
        if not user or not token:
            return False
        if super().check_token(user, token):
            try:
                ts_b64 = token.split('-')[1]
                ts = int(ts_b64, 36)
                now_ts = int(timezone.now().timestamp())
                if (now_ts - ts) > self.timeout:
                    return False
            except Exception:
                return False
            return True
        return False


generate_token = TokenGenerator()
