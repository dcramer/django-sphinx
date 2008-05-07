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

import select
import socket
import time
import struct

try:
    import sphinxapi
except ImportError:
    import api117 as sphinxapi

from django.db.models.query import QuerySet
from django.conf import settings

__all__ = ('SearchError', 'ConnectionError', 'SphinxSearch')

from django.contrib.contenttypes.models import ContentType

# server settings
SPHINX_SERVER           = getattr(settings, 'SPHINX_SERVER', 'localhost')
SPHINX_PORT             = getattr(settings, 'SPHINX_PORT', 3312)

# These require search API 1.19 (Sphinx 0.9.8)
SPHINX_RETRIES          = getattr(settings, 'SPHINX_RETRIES', 0)
SPHINX_RETRIES_DELAY    = getattr(settings, 'SPHINX_RETRIES_DELAY', 5)

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

class SphinxSearch(object):
    def __init__(self, index=None, **kwargs):
        self.init()
        self._index = index
        if 'mode' in kwargs:
            self.mode(kwargs['mode'])
        if 'weights' in kwargs:
            self.weights(kwargs['weights'])
    
    def _clone(self, **kwargs):
        # Clones the queryset passing any changed args
        c = self.__class__()
        c.__dict__.update(self.__dict__)
        c.__dict__.update(kwargs)
        return c
    
    def init(self):
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

        self._filter_range          = None
        self._groupby               = None
        self._sort                  = None
        self._weights               = [1, 100]

        self._maxmatches            = 1000
        self._result_cache          = None
        self._mode                  = sphinxapi.SPH_MATCH_ALL
        self._model                 = None
        self._anchor                = {}
        
    def __get__(self, instance, instance_model, **kwargs):
        if instance != None:
            raise AttributeError, "Manager isn't accessible via %s instances" % type.__name__
        self.init()
        self._model = instance_model
        if not self._index and self._model:
            self._index = self._model._meta.db_table
        return self

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
            if not isinstance(v, list):
                v = [v,]
            v = [isinstance(value, bool) and value and 1 or 0 or int(value) for value in v]
            filters.setdefault(k, []).append(v)

        return self._clone(_filters=filters)

    def geoanchor(self, **kwargs):
        assert(sphinxapi.VER_COMMAND_SEARCH >= 0x113, "You must upgrade sphinxapi to version 1.19 to use Geo Anchoring.")
        return self._clone(_anchor=kwargs)

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

    # Internal methods
    
    def _sphinx(self):
        if not self.__metadata:
            # We have to force execution if this is accessed beforehand
            self._get_data()
        return self.__metadata
    _sphinx = property(_sphinx)

    def _get_data(self):
        assert(self._index)
        assert(self._query)
        # need to find a way to make this work yet
        if self._result_cache is None:
            self._result_cache = list(self._get_results())
        return self._result_cache

    def _get_sphinx_results(self):
        client = sphinxapi.SphinxClient()
        client.SetServer(SPHINX_SERVER, SPHINX_PORT)

        if self._sort:
            client.SetSortMode(*self._sort)

        client.SetWeights(self._weights)

        client.SetMatchMode(self._mode)

        # Include filters
        if self._filters:
            for name, values in self._filters.iteritems():
                for value in values:
                    client.SetFilter(name, value)

        # Exclude filters
        if self._excludes:
            for name, values in self._excludes.iteritems():
                for value in values:
                    client.SetFilter(name, value, exclude=1)
        
        if self._filter_range:
            client.SetIDRange(*self._filter_range)

        if self._groupby:
            client.SetGroupBy(self._groupby, self._groupfunc, self._groupsort)

        if self._anchor:
            client.SetGeoAnchor(self._anchor)

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
            results = [SphinxProxy(queryset[k['id']], {'weight': k['weight']}) for k in results['matches'] if k['id'] in queryset]
        elif results['matches']:
            "We did a query without a model, lets see if there's a content_type"
            if 'content_type' in results['attrs']:
                "Now we have to do one query per content_type"
                x = results['attrs'].index('content_type')
                objcache = {}
                for r in results['matches']:
                    ct = r['attrs'][x]
                    if ct not in objcache:
                        objcache[ct] = {}
                    objcache[ct][r['doc']] = None
                for ct in objcache:
                    qs = ContentType.objects.get(pk=ct).model_class().objects.filter(pk__in=objcache[ct])
                    for o in qs:
                        objcache[ct][o.id] = o
                results = [objcache[r['attrs'][x]][r['doc']] for r in results['matches']]
            else:
                results = results['matches']
        else:
            results = []
        self._result_cache = results
        return results
