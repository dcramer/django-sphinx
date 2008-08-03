from djangosphinx.constants import *

try:
    from sphinxapi import *
except ImportError, exc:
    name = 'djangosphinx.apis.api%d' % (SPHINX_API_VERSION,)
    sphinxapi = __import__(name)
    for name in name.split('.')[1:]:
        sphinxapi = getattr(sphinxapi, name)
    for attr in dir(sphinxapi):
        globals()[attr] = getattr(sphinxapi, attr)
