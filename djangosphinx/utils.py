from django.conf import settings
from django.template import Template, Context

from django.db import models
from django.contrib.contenttypes.models import ContentType

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

# Generate for single models

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

    index_name = model_class._meta.db_table
    
    params.update({
        'index_name': index_name,
        'source_name': index_name,
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
    
    index_name = model_class._meta.db_table
    
    params.update({
        'source_name': index_name,
        'index_name': index_name,
        'table_name': index_name,
        'primary_key': model_class._meta.pk.attname,
        'field_names': [f.attname for f in valid_fields],
        'group_columns': [f.attname for f in valid_fields if f.rel or isinstance(f, models.BooleanField) or isinstance(f, models.IntegerField)],
        'date_columns': [f.attname for f in valid_fields if isinstance(f, models.DateTimeField) or isinstance(f, models.DateField)],
    })
    
    c = Context(params)
    
    return t.render(c)
    
# Generate for multiple models (search UNIONs)

def generate_config_for_models(model_classes, sphinx_params=DEFAULT_SPHINX_PARAMS):
    """
    Generates a sample configuration including an index and source for
    the given model which includes all attributes and date fields.
    """
    return generate_source_for_models(model_classes, sphinx_params) + "\n\n" + generate_index_for_models(model_classes, sphinx_params)

def generate_index_for_models(model_classes, sphinx_params=DEFAULT_SPHINX_PARAMS):
    """Generates a source configmration for a model."""
    fp = open(os.path.join(os.path.dirname(__file__), 'templates/index-multiple.conf'), 'r')
    t = Template(fp.read())
    fp.close()
    
    params = DEFAULT_SPHINX_PARAMS
    
    index_name = '_'.join(m._meta.db_table for m in model_classes)
    
    params.update({
        'index_name': index_name,
        'source_name': index_name,
    })
    
    c = Context(params)
    
    return t.render(c)

def generate_source_for_models(model_classes, sphinx_params=DEFAULT_SPHINX_PARAMS):
    """Generates a source configmration for a model."""
    fp = open(os.path.join(os.path.dirname(__file__), 'templates/source-multiple.conf'), 'r')
    t = Template(fp.read())
    fp.close()
    
    params = DEFAULT_SPHINX_PARAMS
    
    # We need to loop through each model and find only the fields that exist *exactly* the
    # same across models.
    def _the_tuple(f):
        return (f.__class__, f.attname, getattr(f.rel, 'to', None), f.choices)
    
    valid_fields = [_the_tuple(f) for f in model_classes[0]._meta.fields if ((not f.rel or isinstance(f, models.ForeignKey)) and (not isinstance(f, models.IntegerField) or f.choices))]
    for model_class in model_classes[1:]:
        valid_fields = [_the_tuple(f) for f in model_class._meta.fields if _the_tuple(f) in valid_fields]
    
    tables = []
    for model_class in model_classes:
        tables.append((model_class._meta.db_table, ContentType.objects.get_for_model(model_class)))
    
    index_name = '_'.join(m._meta.db_table for m in model_classes)
    
    params.update({
        'tables': tables,
        'source_name': index_name,
        'index_name': index_name,
        'field_names': [f[1] for f in valid_fields],
        'group_columns': [f[1] for f in valid_fields if f[2] or isinstance(f[0], models.BooleanField) or isinstance(f[0], models.IntegerField)],
        'date_columns': [f[1] for f in valid_fields if issubclass(f[0], models.DateTimeField) or issubclass(f[0], models.DateField)],
    })
    
    c = Context(params)
    
    return t.render(c)