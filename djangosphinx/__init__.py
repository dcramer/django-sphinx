"""
Sphinx Search Engine ORM for Django models
http://www.sphinxsearch.com/
Developed and maintained David Cramer <dcramer@gmail.com>

To add a search manager to your model:
<code>
    search = SphinxSearch([index=<string>, weight=[<int>,], mode=<string>])
</code>

To query the engine and retrieve objects:
<code>
    MyModel.search.query('my string')
</code>

To use multiple index support, you need to define a "content_type" field in your SQL
clause. Each index also needs to have the exact same field's. The rules are almost identical
to that of an SQL UNION query.
<code>
    SELECT id, name, 1 as content_type FROM model_myapp
    SELECT id, name, 2 as content_type FROM model_myotherapp
    search_results = SphinxSearch()
    search_results.on_index('model_myapp model_myotherapp')
    search_results.query('hello')
</code>

default settings.py values
<code>
    SPHINX_SERVER = 'localhost'
    SPHINX_PORT = 3312
</code>
"""
import warnings
import os.path

__version__ = (2, 2, 4)

def _get_git_revision(path):
    revision_file = os.path.join(path, 'refs', 'heads', 'master')
    if not os.path.exists(revision_file):
        return None
    fh = open(revision_file, 'r')
    try:
        return fh.read()
    finally:
        fh.close()

def get_revision():
    """
    :returns: Revision number of this branch/checkout, if available. None if
        no revision number can be determined.
    """
    package_dir = os.path.dirname(__file__)
    checkout_dir = os.path.normpath(os.path.join(package_dir, '..'))
    path = os.path.join(checkout_dir, '.git')
    if os.path.exists(path):
        return _get_git_revision(path)
    return None

__build__ = get_revision()

def lazy_object(location):
    def inner(*args, **kwargs):
        parts = location.rsplit('.', 1)
        warnings.warn('`djangosphinx.%s` is deprecated. Please use `%s` instead.' % (parts[1], location), DeprecationWarning)
        imp = __import__(parts[0], globals(), locals(), [parts[1]], -1)
        func = getattr(imp, parts[1])
        if callable(func):
            return func(*args, **kwargs)
        return func
    return inner

SphinxSearch = lazy_object('djangosphinx.models.SphinxSearch')
SphinxQuerySet = lazy_object('djangosphinx.models.SphinxQuerySet')
generate_config_for_model = lazy_object('djangosphinx.utils.generate_config_for_model')
generate_config_for_models = lazy_object('djangosphinx.utils.generate_config_for_models')