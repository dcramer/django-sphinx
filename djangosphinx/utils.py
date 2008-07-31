from django.conf import settings
from django.template import Template, Context

from django.db import models

import os.path

def _get_database_engine():
    if settings.DATABASE_ENGINE == 'mysql':
        return settings.DATABASE_ENGINE
    elif settings.DATABASE_ENGINE.startswith('postgresql'):
        return 'pgsql'
    raise ValueError, "Only MySQL and PostgreSQL engines are supported by Sphinx."

# No trailing slashes on paths
DEFAULT_SPHINX_PARAMS = {
    'database_engine': _get_database_engine(),
    'database_host': settings.DATABASE_HOST,
    'database_port': settings.DATABASE_PORT,
    'database_name': settings.DATABASE_NAME,
    'database_user': settings.DATABASE_USER,
    'database_password': settings.DATABASE_PASSWORD,
    'log_file': '/var/log/sphinx/searchd.log',
    'data_path': '/var/data',
}

def generate_config_for_model(model_class, sphinx_params=DEFAULT_SPHINX_PARAMS):
    """
    Generates a sample configuration including an index and source for
    the given model which includes all attributes and date fields.
    """
    return generate_source_for_model(model_class, sphinx_params) + "\n\n" + generate_index_for_model(model_class, sphinx_params)

def generate_index_for_model(model_class, sphinx_params=DEFAULT_SPHINX_PARAMS):
    """Generates a source configmration for a model."""
    fp = open(os.path.join(os.path.dirname(__file__), 'templates/index.conf'), 'r')
    t = Template(fp.read())
    fp.close()
    
    params = DEFAULT_SPHINX_PARAMS
    
    params.update({
        'table_name': model_class._meta.db_table,
    })
    
    c = Context(params)
    
    return t.render(c)

def generate_source_for_model(model_class, sphinx_params=DEFAULT_SPHINX_PARAMS):
    """Generates a source configmration for a model."""
    fp = open(os.path.join(os.path.dirname(__file__), 'templates/source.conf'), 'r')
    t = Template(fp.read())
    fp.close()
    
    params = DEFAULT_SPHINX_PARAMS
    
    valid_fields = [f for f in model_class._meta.fields if ((not f.rel or isinstance(f, models.ForeignKey)) and (not isinstance(f, models.IntegerField) or f.choices))]
    
    if model_class._meta.pk not in valid_fields:
        valid_fields.insert(0, model_class._meta.pk)
    
    params.update({
        'table_name': model_class._meta.db_table,
        'primary_key': model_class._meta.pk.attname,
        'field_names': [f.attname for f in valid_fields],
        'group_columns': [f.attname for f in valid_fields if f.rel or isinstance(f, models.BooleanField) or isinstance(f, models.IntegerField)],
        'date_columns': [f.attname for f in valid_fields if isinstance(f, models.DateTimeField) or isinstance(f, models.DateField)],
    })
    
    c = Context(params)
    
    return t.render(c)