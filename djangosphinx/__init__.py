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

from manager import *
from utils import generate_config_for_model, generate_config_for_models