from django.conf import settings
from django.template import Template, Context

from django.db import models
from django.contrib.contenttypes.models import ContentType

import os.path

import djangosphinx.apis.current as sphinxapi

__all__ = ('generate_config_for_model', 'generate_config_for_models')

def _get_database_engine():
    if settings.DATABASE_ENGINE == 'mysql':
        return settings.DATABASE_ENGINE
    elif settings.DATABASE_ENGINE.startswith('postgresql'):
        return 'pgsql'
    raise ValueError, "Only MySQL and PostgreSQL engines are supported by Sphinx."

def _get_template(name):
    paths = (
        os.path.join(os.path.dirname(__file__), '../apis/api%s/templates/' % (sphinxapi.VER_COMMAND_SEARCH,)),
        os.path.join(os.path.dirname(__file__), '../templates/'),
    )
    for path in paths:
        try:
            fp = open(path + name, 'r')
        except IOError:
            continue
        try:
            t = Template(fp.read())
            return t
        finally:
            fp.close()
    raise ValueError, "Template matching name does not exist: %s." % (name,)

def _is_sourcable_field(field):
    # We can use float fields in 0.98
    if sphinxapi.VER_COMMAND_SEARCH >= 0x113 and (isinstance(field, models.FloatField) or isinstance(field, models.DecimalField)):
        return True
    elif isinstance(field, models.ForeignKey):
        return True
    elif isinstance(field, models.IntegerField) and field.choices:
        return True
    elif not field.rel:
        return True
    return False

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

def get_index_context(index):
    params = DEFAULT_SPHINX_PARAMS
    params.update({
        'index_name': index,
        'source_name': index,
    })

    return params

def get_source_context(tables, index, valid_fields):
    params = DEFAULT_SPHINX_PARAMS
    params.update({
        'tables': tables,
        'source_name': index,
        'index_name': index,
        'database_engine': _get_database_engine(),
        'field_names': [f[1] for f in valid_fields],
        'group_columns': [f[1] for f in valid_fields if f[2] or isinstance(f[0], models.BooleanField) or isinstance(f[0], models.IntegerField)],
        'date_columns': [f[1] for f in valid_fields if issubclass(f[0], models.DateTimeField) or issubclass(f[0], models.DateField)],
        'float_columns': [f[1] for f in valid_fields if isinstance(f[0], models.FloatField) or isinstance(f[0], models.DecimalField)],
    })
    try:
        from django.contrib.gis.db.models import PointField
        params.update({
            'gis_columns': [f.column for f in valid_fields if isinstance(f, PointField)],
            'srid': getattr(settings, 'GIS_SRID', 4326), # reasonable lat/lng default
        })
        if params['database_engine'] == 'pgsql' and params['gis_columns']:
            params['field_names'].extend(["radians(ST_X(ST_Transform(%(field_name)s, %(srid)s))) AS %(field_name)s_longitude, radians(ST_Y(ST_Transform(%(field_name)s, %(srid)s))) AS %(field_name)s_latitude" % {'field_name': f, 'srid': params['srid']} for f in params['gis_columns']])
    except ImportError:
        # GIS not supported
        pass
    return params

# Generate for single models

def generate_config_for_model(model_class, index=None, sphinx_params={}):
    """
    Generates a sample configuration including an index and source for
    the given model which includes all attributes and date fields.
    """
    return generate_source_for_model(model_class, index, sphinx_params) + "\n\n" + generate_index_for_model(model_class, index, sphinx_params)

def generate_index_for_model(model_class, index=None, sphinx_params={}):
    """Generates a source configmration for a model."""
    t = _get_template('index.conf')
    
    if index is None:
        index = model_class._meta.db_table
    
    params = get_index_context(index)
    params.update(sphinx_params)
    
    c = Context(params)
    
    return t.render(c)

def generate_source_for_model(model_class, index=None, sphinx_params={}):
    """Generates a source configmration for a model."""
    t = _get_template('source.conf')

    def _the_tuple(f):
        return (f.__class__, f.column, getattr(f.rel, 'to', None), f.choices)

    valid_fields = [_the_tuple(f) for f in model_class._meta.fields if _is_sourcable_field(f)]
    
    table = model_class._meta.db_table
    
    if index is None:
        index = table
        
    params = get_source_context([table], index, valid_fields)
    params.update({
        'table_name': table,
        'primary_key': model_class._meta.pk.column,
    })
    params.update(sphinx_params)

    c = Context(params)
    
    return t.render(c)
    
# Generate for multiple models (search UNIONs)

def generate_config_for_models(model_classes, index=None, sphinx_params={}):
    """
    Generates a sample configuration including an index and source for
    the given model which includes all attributes and date fields.
    """
    return generate_source_for_models(model_classes, index, sphinx_params) + "\n\n" + generate_index_for_models(model_classes, index, sphinx_params)

def generate_index_for_models(model_classes, index=None, sphinx_params={}):
    """Generates a source configmration for a model."""
    t = _get_template('index-multiple.conf')
    
    if index is None:
        index = '_'.join(m._meta.db_table for m in model_classes)
    
    params = get_index_context(index)
    params.update(sphinx_params)
    
    c = Context(params)
    
    return t.render(c)

def generate_source_for_models(model_classes, index=None, sphinx_params={}):
    """Generates a source configmration for a model."""
    t = _get_template('source-multiple.conf')
    
    # We need to loop through each model and find only the fields that exist *exactly* the
    # same across models.
    def _the_tuple(f):
        return (f.__class__, f.column, getattr(f.rel, 'to', None), f.choices)
    
    valid_fields = [_the_tuple(f) for f in model_classes[0]._meta.fields if _is_sourcable_field(f)]
    for model_class in model_classes[1:]:
        valid_fields = [_the_tuple(f) for f in model_class._meta.fields if _the_tuple(f) in valid_fields]
    
    tables = []
    for model_class in model_classes:
        tables.append((model_class._meta.db_table, ContentType.objects.get_for_model(model_class)))
    
    if index is None:
        index = '_'.join(m._meta.db_table for m in model_classes)
    
    params = get_source_context(tables, index, valid_fields)
    params.update(sphinx_params)

    c = Context(params)
    
    return t.render(c)