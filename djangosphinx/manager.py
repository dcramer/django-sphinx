import select
import socket
import time
import struct
import warnings
import apis.current as sphinxapi

from django.db.models.query import QuerySet
from django.conf import settings

__all__ = ('SearchError', 'ConnectionError', 'SphinxSearch', 'SphinxRelation')

from django.contrib.contenttypes.models import ContentType
from datetime import datetime, date

# server settings
SPHINX_SERVER           = getattr(settings, 'SPHINX_SERVER', 'localhost')
SPHINX_PORT             = getattr(settings, 'SPHINX_PORT', 3312)

# These require search API 1.19 (Sphinx 0.9.8)
SPHINX_RETRIES          = getattr(settings, 'SPHINX_RETRIES', 0)
SPHINX_RETRIES_DELAY    = getattr(settings, 'SPHINX_RETRIES_DELAY', 5)

MAX_INT = int(2**31-1)

class SearchError(Exception): pass
class ConnectionError(Exception): pass

class SphinxProxy(object):
    """
    Acts exactly like a normal instance of an object except that
    it will handle any special sphinx attributes in a _sphinx class.
    """
    __slots__ = ('__dict__', '__instance__', '_sphinx')

    def __init__(self, instance, attributes):
        object.__setattr__(self, '__instance__', instance)
        object.__setattr__(self, '_sphinx', attributes)

    def _get_current_object(self):
        """
        Return the current object.  This is useful if you want the real object
        behind the proxy at a time for performance reasons or because you want
        to pass the object into a different context.
        """
        return self.__instance__
    __current_object = property(_get_current_object)

    def __dict__(self):
        try:
            return self.__current_object.__dict__
        except RuntimeError:
            return AttributeError('__dict__')
    __dict__ = property(__dict__)

    def __repr__(self):
        try:
            obj = self.__current_object
        except RuntimeError:
            return '<%s unbound>' % self.__class__.__name__
        return repr(obj)

    def __nonzero__(self):
        try:
            return bool(self.__current_object)
        except RuntimeError:
            return False

    def __unicode__(self):
        try:
            return unicode(self.__current_oject)
        except RuntimeError:
            return repr(self)

    def __dir__(self):
        try:
            return dir(self.__current_object)
        except RuntimeError:
            return []

    def __getattr__(self, name, value=None):
        if name == '__members__':
            return dir(self.__current_object)
        elif name == '_sphinx':
            return object.__getattr__(self, '_sphinx', value)
        return getattr(self.__current_object, name)

    def __setattr__(self, name, value):
        if name == '_sphinx':
            return object.__setattr__(self, '_sphinx', value)
        return setattr(self.__current_object, name, value)

    def __setitem__(self, key, value):
        self.__current_object[key] = value

    def __delitem__(self, key):
        del self.__current_object[key]

    def __setslice__(self, i, j, seq):
        self.__current_object[i:j] = seq

    def __delslice__(self, i, j):
        del self.__current_object[i:j]

    __delattr__ = lambda x, n: delattr(x.__current_object, n)
    __str__ = lambda x: str(x.__current_object)
    __unicode__ = lambda x: unicode(x.__current_object)
    __lt__ = lambda x, o: x.__current_object < o
    __le__ = lambda x, o: x.__current_object <= o
    __eq__ = lambda x, o: x.__current_object == o
    __ne__ = lambda x, o: x.__current_object != o
    __gt__ = lambda x, o: x.__current_object > o
    __ge__ = lambda x, o: x.__current_object >= o
    __cmp__ = lambda x, o: cmp(x.__current_object, o)
    __hash__ = lambda x: hash(x.__current_object)
    __call__ = lambda x, *a, **kw: x.__current_object(*a, **kw)
    __len__ = lambda x: len(x.__current_object)
    __getitem__ = lambda x, i: x.__current_object[i]
    __iter__ = lambda x: iter(x.__current_object)
    __contains__ = lambda x, i: i in x.__current_object
    __getslice__ = lambda x, i, j: x.__current_object[i:j]
    __add__ = lambda x, o: x.__current_object + o
    __sub__ = lambda x, o: x.__current_object - o
    __mul__ = lambda x, o: x.__current_object * o
    __floordiv__ = lambda x, o: x.__current_object // o
    __mod__ = lambda x, o: x.__current_object % o
    __divmod__ = lambda x, o: x.__current_object.__divmod__(o)
    __pow__ = lambda x, o: x.__current_object ** o
    __lshift__ = lambda x, o: x.__current_object << o
    __rshift__ = lambda x, o: x.__current_object >> o
    __and__ = lambda x, o: x.__current_object & o
    __xor__ = lambda x, o: x.__current_object ^ o
    __or__ = lambda x, o: x.__current_object | o
    __div__ = lambda x, o: x.__current_object.__div__(o)
    __truediv__ = lambda x, o: x.__current_object.__truediv__(o)
    __neg__ = lambda x: -(x.__current_object)
    __pos__ = lambda x: +(x.__current_object)
    __abs__ = lambda x: abs(x.__current_object)
    __invert__ = lambda x: ~(x.__current_object)
    __complex__ = lambda x: complex(x.__current_object)
    __int__ = lambda x: int(x.__current_object)
    __long__ = lambda x: long(x.__current_object)
    __float__ = lambda x: float(x.__current_object)
    __oct__ = lambda x: oct(x.__current_object)
    __hex__ = lambda x: hex(x.__current_object)
    __index__ = lambda x: x.__current_object.__index__()
    __coerce__ = lambda x, o: x.__coerce__(x, o)
    __enter__ = lambda x: x.__enter__()
    __exit__ = lambda x, *a, **kw: x.__exit__(*a, **kw)

def to_sphinx(value):
    "Convert a value into a sphinx query value"
    if isinstance(value, date) or isinstance(value, datetime):
        return int(time.mktime(value.timetuple()))
    return int(value)

class SphinxQuerySet(object):
    available_kwargs = ('rankmode', 'mode', 'weights')
    
    def __init__(self, model=None, **kwargs):
        self._select_related        = False
        self._select_related_args   = {}
        self._select_related_fields = []
        self._filters               = {}
        self._excludes              = {}
        self._extra                 = {}
        self._query                 = ''
        self.__metadata             = None
        self._offset                = 0
        self._limit                 = 20

        self._groupby               = None
        self._sort                  = None
        self._weights               = [1, 100]

        self._maxmatches            = 1000
        self._result_cache          = None
        self._mode                  = sphinxapi.SPH_MATCH_ALL
        self._rankmode              = getattr(sphinxapi, 'SPH_RANK_PROXIMITY_BM25', None)
        self._model                 = model
        self._anchor                = {}
        
        for key in self.available_kwargs:
            if key in kwargs:
                setattr(self, '_%s' % (key,), kwargs[key])

        if model:
            self._index             = kwargs.get('index', model._meta.db_table)
        else:
            self._index             = kwargs.get('index')

    def __repr__(self):
        if self._result_cache is not None:
            return repr(self._get_data())
        else:
            return '<%s instance>' % (self.__class__.__name__,)

    def __len__(self):
        return len(self._get_data())
        
    def __iter__(self):
        return iter(self._get_data())
    
    def __getitem__(self, k):
        if not isinstance(k, (slice, int)):
            raise TypeError
        assert (not isinstance(k, slice) and (k >= 0)) \
            or (isinstance(k, slice) and (k.start is None or k.start >= 0) and (k.stop is None or k.stop >= 0)), \
            "Negative indexing is not supported."
        if type(k) == slice:
            if self._offset < k.start or k.stop-k.start > self._limit:
                self._result_cache = None
        else:
            if k not in range(self._offset, self._limit+self._offset):
                self._result_cache = None
        if self._result_cache is None:
            if type(k) == slice:
                self._offset = k.start
                self._limit = k.stop-k.start
                return self._get_results()
            else:
                self._offset = k
                self._limit = 1
                return self._get_results()[0]
        else:
            return self._result_cache[k]

    def rank_none(self):
        return self._clone(_rankmode=sphinxapi.SPH_RANK_NONE)

    def query(self, string):
        return self._clone(_query=unicode(string).encode('utf-8'))

    def mode(self, mode):
        return self._clone(_mode=mode)

    def group_by(self, attribute, func, groupsort='@group desc'):
        return self._clone(_groupby=attribute, _groupfunc=func, _groupsort=groupsort)

    def weights(self, weights):
        return self._clone(_weights=weights)

    # only works on attributes
    def filter(self, **kwargs):
        filters = self._filters.copy()
        for k,v in kwargs.iteritems():
            if hasattr(v, 'next'):
                v = list(v)
            elif not (isinstance(v, list) or isinstance(v, tuple)):
                 v = [v,]
            filters.setdefault(k, []).extend(map(to_sphinx, v))
        return self._clone(_filters=filters)

    def geoanchor(self, lat_attr, lng_attr, lat, lng):
        assert(sphinxapi.VER_COMMAND_SEARCH >= 0x113, "You must upgrade sphinxapi to version 1.19 to use Geo Anchoring.")
        return self._clone(_anchor=(lat_attr, lng_attr, float(lat), float(lng)))

    def on_index(self, index):
        return self._clone(_index=index)

    # this actually does nothing, its just a passthru to
    # keep things looking/working generally the same
    def all(self):
        return self

    # only works on attributes
    def exclude(self, **kwargs):
        filters = self._excludes.copy()
        for k,v in kwargs.iteritems():
            if not isinstance(v, list):
                v = [v,]
            v = [isinstance(value, bool) and value and 1 or 0 or int(value) for value in v]
            filters.setdefault(k, []).append(v)

        return self._clone(_excludes=filters)

    # you cannot order by @weight (it always orders in descending)
    # keywords are @id, @weight, @rank, and @relevance
    def order_by(self, *args):
        sort_by = []
        for arg in args:
            sort = 'ASC'
            if arg[0] == '-':
                arg = arg[1:]
                sort = 'DESC'
            if arg == 'id':
                arg = '@id'
            sort_by.append('%s %s' % (arg, sort))
        if sort_by:
            return self._clone(_sort=(sphinxapi.SPH_SORT_EXTENDED, ', '.join(sort_by)))
        return self
                    
    # pass these thru on the queryset and let django handle it
    def select_related(self, *args, **kwargs):
        _args = self._select_related_fields[:]
        _args.extend(args)
        _kwargs = self._select_related_args.copy()
        _kwargs.update(kwargs)
        
        return self._clone(
            _select_related=True,
            _select_related_fields=_args,
            _select_related_args=_kwargs,
        )
    
    def extra(self, **kwargs):
        extra = self._extra.copy()
        extra.update(kwargs)
        return self._clone(_extra=extra)

    def count(self):
        return self._get_sphinx_results()['total_found']

    def reset(self):
        return self.__class__(self._model, self._index)

    # Internal methods
    def _clone(self, **kwargs):
        # Clones the queryset passing any changed args
        c = self.__class__()
        c.__dict__.update(self.__dict__)
        c.__dict__.update(kwargs)
        return c
    
    def _sphinx(self):
        if not self.__metadata:
            # We have to force execution if this is accessed beforehand
            self._get_data()
        return self.__metadata
    _sphinx = property(_sphinx)

    def _get_data(self):
        assert(self._index)
        # need to find a way to make this work yet
        if self._result_cache is None:
            self._result_cache = list(self._get_results())
        return self._result_cache

    def _get_sphinx_results(self):
        client = sphinxapi.SphinxClient()
        client.SetServer(SPHINX_SERVER, SPHINX_PORT)

        if self._sort:
            client.SetSortMode(*self._sort)
        
        if isinstance(self._weights, list) or isinstance(self._weights, tuple):
            client.SetWeights(self._weights)
        else:
            # assume its a dict
            client.SetFieldWeights(self._weights)
        
        client.SetMatchMode(self._mode)

        if hasattr(client, 'ResetFilter'):
                    # TODO: convince Sphinx guy to change this ugliness
                    client.ResetFilter()
        
        def _handle_filters(filter_list, exclude=False):
            for name, values in filter_list.iteritems():
                parts = len(name.split('__'))
                if parts > 2:
                    raise NotImplementedError, 'Related object and/or multiple field lookups not supported'
                elif parts == 2:
                    # The float handling for __gt and __lt is kind of ugly..
                    name, lookup = name.split('__', 1)
                    is_float = isinstance(values[0], float)
                    if lookup == 'gt':
                        value = is_float and values[0] + (1.0/MAX_INT) or values[0] - 1
                        args = (name, value, MAX_INT, exclude)
                    elif lookup == 'gte':
                        args = (name, values[0], MAX_INT, exclude)
                    elif lookup == 'lt':
                        value = is_float and values[0] - (1.0/MAX_INT) or values[0] - 1
                        args = (name, -MAX_INT, value, exclude)
                    elif lookup == 'lte':
                        args = (name, -MAX_INT, values[0], exclude)
                    elif lookup == 'range':
                        args = (name, values[0], values[1], exclude)
                    else:
                        raise NotImplementedError, 'Related object and/or field lookup "%s" not supported' % lookup
                    if is_float:
                        client.SetFilterFloatRange(*args)
                    elif not exclude and self._model and name == self._model._meta.pk.column:
                        client.SetIDRange(*args[1:3])
                    else:
                        client.SetFilterRange(*args)

                else:
                    client.SetFilter(name, values, exclude)

        # Include filters
        if self._filters:
            _handle_filters(self._filters)

        # Exclude filters
        if self._excludes:
            _handle_filters(self.self._excludes, True)
        
        if self._groupby:
            client.SetGroupBy(self._groupby, self._groupfunc, self._groupsort)

        if self._anchor:
            client.SetGeoAnchor(*self._anchor)

        if self._rankmode:
            client.SetRankingMode(self._rankmode)

        if not self._limit > 0:
            # Fix for Sphinx throwing an assertion error when you pass it an empty limiter
            return []
        
        client.SetLimits(self._offset, self._limit, max(self._limit, self._maxmatches))
        if sphinxapi.VER_COMMAND_SEARCH >= 0x113:
            client.SetRetries(SPHINX_RETRIES, SPHINX_RETRIES_DELAY)
        
        results = client.Query(self._query, self._index)
        
        # The Sphinx API doesn't raise exceptions
        if not results:
            if client.GetLastError():
                raise SearchError, client.GetLastError()
            elif client.GetLastWarning():
                raise SearchError, client.GetLastWarning()
        return results

    def _get_results(self):
        results = self._get_sphinx_results()
        if not results: return []
        if results['matches'] and self._model:
            qs = self._model.objects.filter(pk__in=[r['id'] for r in results['matches']])
            if self._select_related:
                qs = qs.select_related(*self._select_related_fields, **self._select_related_args)
            if self._extra:
                qs = qs.extra(**self._extra)
            queryset = dict([(o.id, o) for o in qs])
            self.__metadata = {
                'total': results['total'],
                'total_found': results['total_found'],
                'words': results['words'],
            }
            results = [SphinxProxy(queryset[k['id']], k) for k in results['matches'] if k['id'] in queryset]
        elif results['matches']:
            "We did a query without a model, lets see if there's a content_type"
            results['attrs'] = dict(results['attrs'])
            if 'content_type' in results['attrs']:
                "Now we have to do one query per content_type"
                objcache = {}
                for r in results['matches']:
                    ct = r['attrs']['content_type']
                    if ct not in objcache:
                        objcache[ct] = {}
                    objcache[ct][r['id']] = None
                for ct in objcache:
                    qs = ContentType.objects.get(pk=ct).model_class().objects.filter(pk__in=objcache[ct])
                    for o in qs:
                        objcache[ct][o.id] = o
                results = [objcache[r['attrs']['content_type']][r['id']] for r in results['matches']]
            else:
                results = results['matches']
        else:
            results = []
        self._result_cache = results
        return results

class SphinxModelManager(object):
    def __init__(self, model, **kwargs):
        self._model = model
        self._index = kwargs.pop('index', model._meta.db_table)
        self._kwargs = kwargs
    
    def _get_query_set(self):
        return SphinxQuerySet(self._model, index=self._index, **self._kwargs)
    
    def get_index(self):
        return self._index
    
    def all(self):
        return self._get_query_set()
    
    def filter(self, **kwargs):
        return self._get_query_set().filter(**kwargs)
    
    def query(self, *args, **kwargs):
        return self._get_query_set().query(*args, **kwargs)

    def on_index(self, *args, **kwargs):
        return self._get_query_set().on_index(*args, **kwargs)

    def geoanchor(self, *args, **kwargs):
        return self._get_query_set().geoanchor(*args, **kwargs)

class SphinxInstanceManager(object):
    """Collection of tools useful for objects which are in a Sphinx index."""
    def __init__(self, instance, index):
        self._instance = instance
        self._index = index
        
    def update(self, **kwargs):
        assert(sphinxapi.VER_COMMAND_SEARCH >= 0x113, "You must upgrade sphinxapi to version 1.19 to use Geo Anchoring.")
        sphinxapi.UpdateAttributes(index, kwargs.keys(), dict(self.instance.pk, map(to_sphinx, kwargs.values())))


class SphinxSearch(object):
    def __init__(self, index=None, **kwargs):
        self._kwargs = kwargs
        self._sphinx = None
        self._index = index
        self.model = None
        
    def __call__(self, index, **kwargs):
        warnings.warn('For non-model searches use a SphinxQuerySet instance.', DeprecationWarning)
        return SphinxQuerySet(index=index, **kwargs)
        
    def __get__(self, instance, model, **kwargs):
        if instance:
            return SphinxInstanceManager(instance, index)
        return self._sphinx

    def contribute_to_class(self, model, name, **kwargs):
        if self._index is None:
            self._index = model._meta.db_table
        self._sphinx = SphinxModelManager(model, index=self._index, **self._kwargs)
        self.model = model
        if getattr(model, '__sphinx_indexes__', None) is None:
            setattr(model, '__sphinx_indexes__', [self._index])
        else:
            model.__sphinx_indexes__.append(self._index)
        setattr(model, name, self._sphinx)

class SphinxRelationProxy(SphinxProxy):
    def count(self):
        return self._sphinx['attrs']['@count']
    
class SphinxRelation(SphinxSearch):
    """
    Adds "related model" support to django-sphinx --
    http://code.google.com/p/django-sphinx/
    http://www.sphinxsearch.com/
    
    Example --
    
    class MySearch(SphinxSearch):
        myrelatedobject = SphinxRelation(RelatedModel)
        anotherone = SphinxRelation(AnotherModel)
        ...
    
    class MyModel(models.Model):
        search = MySearch('index')
    
    """
    def __init__(self, model=None, attr=None, sort='@count desc', **kwargs):
        if model:
            self._related_model = model
            self._related_attr = attr or model.__name__.lower()
            self._related_sort = sort
        super(SphinxRelation, self).__init__(**kwargs)
        
    def __get__(self, instance, instance_model, **kwargs):
        self._mode = instance._mode
        self._rankmode = instance._rankmode
        self._index = instance._index
        self._query = instance._query
        self._filters = instance._filters
        self._model = self._related_model
        self._groupby = self._related_attr
        self._groupsort = self._related_sort
        self._groupfunc = sphinxapi.SPH_GROUPBY_ATTR
        return self

    def _get_results(self):
        results = self._get_sphinx_results()
        if not results: return []
        if results['matches'] and self._model:
            ids = []
            for r in results['matches']:
                value = r['attrs']['@groupby']
                if isinstance(value, int):
                    ids.append(value)
                else:
                    ids.extend()
            qs = self._model.objects.filter(pk__in=set(ids))
            if self._select_related:
                qs = qs.select_related(*self._select_related_fields,
                                       **self._select_related_args)
            if self._extra:
                qs = qs.extra(**self._extra)
            queryset = dict([(o.id, o) for o in qs])
            self.__metadata = {
                'total': results['total'],
                'total_found': results['total_found'],
                'words': results['words'],
            }
            results = [ SphinxRelationProxy(queryset[k['attrs']['@groupby']], k) \
                        for k in results['matches'] \
                        if k['attrs']['@groupby'] in queryset ]
        else:
            results = []
        self._result_cache = results
        return results

    def _sphinx(self):
        if not self.__metadata:
            # We have to force execution if this is accessed beforehand
            self._get_data()
        return self.__metadata
    _sphinx = property(_sphinx)