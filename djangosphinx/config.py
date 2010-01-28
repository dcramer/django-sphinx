#!/usr/bin/env python

import os, sys, os.path, warnings

# Add the project to the python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# Set our settings module
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    raise ValueError('`DJANGO_SETTINGS_MODULE` was not set. Please use DJANGO_SETTINGS_MODULE=project.settings <command> --config sphinx.py.')

from django.conf import settings

assert getattr(settings, 'SPHINX_ROOT', None) is not None, "You must specify `SPHINX_ROOT` in your settings."

from django.template import RequestContext

if 'coffin' in settings.INSTALLED_APPS:
    import jinja2
    from coffin import shortcuts
else:
    from django import shortcuts
    
def render_to_string(template, context, request=None):
    if request:
        context_instance = RequestContext(request)
    else:
        context_instance = None
    return shortcuts.render_to_string(template, context, context_instance)

def relative_path(*args):
    return os.path.abspath(os.path.join(settings.SPHINX_ROOT, *args))

context = {
    'SPHINX_HOST': getattr(settings, 'SPHINX_HOST', '127.0.0.1'),
    'SPHINX_PORT': getattr(settings, 'SPHINX_PORT', '3312'),
    'relative_path': relative_path,
}
if getattr(settings, 'DATABASES', None):
    context.update({
        'DATABASE_HOST': settings.DATABASES['default']['HOST'],
        'DATABASE_PASSWORD': settings.DATABASES['default']['PASSWORD'],
        'DATABASE_USER': settings.DATABASES['default']['USER'],
        'DATABASE_PORT': settings.DATABASES['default']['PORT'],
        'DATABASE_NAME': settings.DATABASES['default']['NAME'],
    })
else:
    context.update({
        'DATABASE_HOST': settings.DATABASE_HOST,
        'DATABASE_PASSWORD': settings.DATABASE_PASSWORD,
        'DATABASE_USER': settings.DATABASE_USER,
        'DATABASE_PORT': settings.DATABASE_PORT,
        'DATABASE_NAME': settings.DATABASE_NAME,
    })

print render_to_string(getattr(settings, 'SPHINX_CONFIG_TEMPLATE', 'conf/sphinx.conf'), context)
