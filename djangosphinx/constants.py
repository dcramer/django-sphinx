from django.conf import settings

__all__ = ('SPHINX_API_VERSION',)

# 0x113 = 1.19
# 0x107 = 1.17
SPHINX_API_VERSION = getattr(settings, 'SPHINX_API_VERSION', 0x107)