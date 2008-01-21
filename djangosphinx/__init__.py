"""
Sphinx Search Engine ORM for Django models
http://www.sphinxsearch.com/
Developed and maintained
by Curse (http://www.curse.com/)

To add a search manage to your model:
search = SphinxSearch([index=<string>, weight=[<int>,], mode=<string>])

To query the engine and retrieve objects:
MyModel.search.query('my string')

settings.py should contain:
SPHINX_SERVER = 'localhost'
SPHINX_PORT = 3312
"""

import select, socket, time
from struct import *
from django.conf import settings

# If you don't want multiple index support you can comment this line
# For indexes used in these queries you will need them to all have the
# same attributes, and an additional content_type attribute which
# is set as the content_type id of that model
# e.g.
# SELECT id, name, 1 as content_type FROM model_myapp
# SELECT id, name, 2 as content_type FROM model_myotherapp
# SphinxSearch().query('hello').on_index('model_myapp model_myotherapp')
from django.contrib.contenttypes.models import ContentType

# known searchd commands
SEARCHD_COMMAND_SEARCH	= 0
SEARCHD_COMMAND_EXCERPT	= 1

# current client-side command implementation versions
VER_COMMAND_SEARCH		= 0x107
VER_COMMAND_EXCERPT		= 0x100

# known searchd status codes
SEARCHD_OK				= 0
SEARCHD_ERROR			= 1
SEARCHD_RETRY			= 2
SEARCHD_WARNING			= 3

# known match modes
SPH_MATCH_ALL			= 0
SPH_MATCH_ANY			= 1
SPH_MATCH_PHRASE		= 2
SPH_MATCH_BOOLEAN		= 3
SPH_MATCH_EXTENDED		= 4

# known sort modes
SPH_SORT_RELEVANCE		= 0
SPH_SORT_ATTR_DESC		= 1
SPH_SORT_ATTR_ASC		= 2
SPH_SORT_TIME_SEGMENTS	= 3
SPH_SORT_EXTENDED		= 4

# known attribute types
SPH_ATTR_INTEGER		= 1
SPH_ATTR_TIMESTAMP		= 2

# known grouping functions
SPH_GROUPBY_DAY	 		= 0
SPH_GROUPBY_WEEK		= 1
SPH_GROUPBY_MONTH		= 2
SPH_GROUPBY_YEAR		= 3
SPH_GROUPBY_ATTR		= 4

# retries and wait time inbetween retries
# (not a true timeout)
SPH_RETRIES 			= 3
SPH_TIMEOUT				= 1

class SearchError(Exception):
	def __init__(self, message):
		self.message = message

	def __str__(self):
		return str(self.message)

class ConnectionError(Exception):
	def __init__(self, message):
		self.message = message

	def __str__(self):
		return str(self.message)

class SphinxSearch(object):
	def __init__(self, index=None, **kwargs):
		self.init()
		if index:
			self._index = index
		else:
			self._index = None
		if 'mode' in kwargs:
			self.mode(kwargs['mode'])
		if 'weights' in kwargs:
			self.weights(kwargs['weights'])
			
	def init(self):
		self._select_related 		= False
		self._select_related_args 	= {}
		self._select_related_fields = []
		self._filters 				= {}
		self._excludes				= {}
		self._extra					= {}
		self._query 				= ''
		self._offset 				= 0
		self._limit 				= 20
		self._min_id 				= 0 # we dont use this currently
		self._max_id 				= 0xFFFFFFFF # dont use this either
		self._maxmatches			= 1000
		self._sort 					= SPH_SORT_RELEVANCE
		self._sortby 				= 'desc'
		self._groupby				= ''
		self._groupfunc				= SPH_GROUPBY_DAY
		self._groupsort				= '@group desc'
		self._result_cache			= None
		self._weights				= [100, 1]
		self._mode					= SPH_MATCH_EXTENDED
		self._model 				= None
		
	def __get__(self, instance, instance_model, **kwargs):
		if instance != None:
			raise AttributeError, "Manager isn't accessible via %s instances" % type.__name__
		self.init()
		self._model = instance_model
		if not self._index and self._model:
			self._index = self._model._meta.db_table
		return self

	def __repr__(self):
		return repr(self._get_data())
				
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

	def _get_data(self):
		assert(self._index)
		assert(self._query)
		# need to find a way to make this work yet
		if self._result_cache is None:
			self._result_cache = list(self._get_results())
		return self._result_cache

	def query(self, string):
		self._query = unicode(string)
		return self

	def mode(self, mode):
		assert(mode in [SPH_MATCH_ALL, SPH_MATCH_ANY, SPH_MATCH_PHRASE, SPH_MATCH_BOOLEAN, SPH_MATCH_EXTENDED])
		self._mode = mode
		return self

	def group_by(self, attribute, func, groupsort='@group desc'):
		assert(isinstance(attribute, str))
		assert(func in [SPH_GROUPBY_DAY, SPH_GROUPBY_WEEK, SPH_GROUPBY_MONTH, SPH_GROUPBY_YEAR, SPH_GROUPBY_ATTR] )
		assert(isinstance(groupsort, str))
		self._groupby = attribute
		self._groupfunc = func
		self._groupsort = groupsort
		return self

	def weights(self, weights):
		assert(isinstance(weights, list))
		for w in weights:
			assert(isinstance(w, int))
		self._weights = weights

	# only works on attributes
	def filter(self, **kwargs):
		for k,v in kwargs.iteritems():
			assert(isinstance(k, str))
			assert(v != None)
			if not isinstance(v, list):
				v = [v,]
			v = [isinstance(value, bool) and value and 1 or 0 or int(value) for value in v]
			if not k in self._filters:
				self._filters[k] = []
			if v not in self._filters[k]:
				self._filters[k] += v
		return self

	def on_index(self, index):
		self._index = index
		return self

	# this actually does nothing, its just a passthru to
	# keep things looking/working generally the same
	def all(self):
		return self

	# only works on attributes
	def exclude(self, **kwargs):
		for k,v in kwargs.iteritems():
			assert(isinstance(k, str))
			assert(v != None)
			if not isinstance(v, list):
				v = [v,]
			v = [isinstance(value, bool) and value and 1 or 0 or int(value) for value in v]
			if not k in self._excludes:
				self._excludes[k] = []
			if v not in self._excludes[k]:
				self._excludes[k] += v
		return self

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
			assert(isinstance(arg, str))
			sort_by.append('%s %s' % (arg, sort))
		if sort_by:
			self._sort = SPH_SORT_EXTENDED
			self._sortby = ', '.join(sort_by)
		return self
					
	# pass these thru on the queryset and let django handle it
	def select_related(self, *args, **kwargs):
		self._select_related = True
		self._select_related_fields += args
		self._select_related_args.update(**kwargs)
		return self
		
	# SphinxAPI
	def _connect(self):
		"""
		connect to searchd server
		"""
		i = 0
		while True:
			try:
				sock = socket.socket (socket.AF_INET, socket.SOCK_STREAM)
				sock.connect((settings.SPHINX_SERVER, settings.SPHINX_PORT))
			except socket.error, msg:
				i += 1
				if sock:
					sock.close()
				if i >= SPH_RETRIES:
					raise ConnectionError, 'connection to %s:%s failed (%s)' % (settings.SPHINX_SERVER, settings.SPHINX_PORT, msg)
				time.sleep(SPH_TIMEOUT)
			else:
				break
		v = unpack('>L', sock.recv(4))
		if v < 1:
			sock.close()
			raise SearchError, 'expected searchd protocol version, got %s' % v
		# all ok, send my version
		sock.send(pack('>L', 1))
		return sock

	def _get_response(self, sock, client_ver):
		"""
		get and check response packet from searchd server
		"""
		(status, ver, length) = unpack('>2HL', sock.recv(8))
		response = ''
		left = length
		while left > 0:
			chunk = sock.recv(left)
			if chunk:
				response += chunk
				left -= len(chunk)
			else:
				break
		sock.close()

		# check response
		read = len(response)
		if not response or read != length:
			if length:
				raise SearchError, 'failed to read searchd response (status=%s, ver=%s, len=%s, read=%s)' \
					% (status, ver, length, read)
			raise SearchError, 'received zero-sized searchd response'

		# check status
		if status == SEARCHD_WARNING:
			wend = 4 + unpack ( '>L', response[0:4] )[0]
			self._warning = response[4:wend]
			return response[wend:]
		elif status == SEARCHD_ERROR:
			raise SearchError, 'searchd error: '+response[4:]
		elif status == SEARCHD_RETRY:
			raise SearchError, 'temporary searchd error: '+response[4:]
		elif status != SEARCHD_OK:
			raise SearchError, 'unknown status code %d' % status

		# check version
		if ver < client_ver:
			self._warning = 'searchd command v.%d.%d older than client\'s v.%d.%d, some options might not work' \
				% (ver>>8, ver&0xff, client_ver>>8, client_ver&0xff)
		return response

	def _get_sphinx_results(self):
		sock = self._connect()
		if not sock:
			raise SearchError, "unknown error trying to connect"

		# build request
		req = [pack('>4L', self._offset, self._limit, self._mode, self._sort)]
		req.append(pack('>L', len(self._sortby)))
		req.append(self._sortby)
		q = self._query.encode('utf-8')
		req.append(pack('>L', len(q)))
		req.append(q)
		req.append(pack('>L', len(self._weights)))
		for w in self._weights:
			req.append(pack('>L', w))
		req.append(pack('>L', len(self._index)))
		req.append(self._index)
		req.append(pack('>L', self._min_id))
		req.append(pack('>L', self._max_id))
		# filters
		req.append(pack('>L', len(self._filters)+len(self._excludes)))
		for k,vl in self._filters.iteritems():
			req.append(pack('>L', len(k)))
			req.append(k)
			req.append(pack('>L', len(vl)))
			for v in vl:
				req.append(pack('>L', v))
#			req.append(pack('>3L', 0, f['min'], f['max'])) -- this seems useless, dont think we need support
			req.append(pack('>L', 0))
		for k,v in self._excludes.iteritems():
			req.append(pack('>L', len(k)))
			req.append(k)
			req.append(pack('>L', len(vl)))
			for v in vl:
				req.append(pack('>L', v))
			req.append(pack('>L', 1))

		# group-by, max-matches, group-sort
		req.append(pack('>2L', self._groupfunc, len(self._groupby)))
		req.append(self._groupby)
		req.append(pack('>2L', self._maxmatches, len(self._groupsort)))
		req.append(self._groupsort)

		# send query, get response
		req = ''.join(req)

		length = len(req)
		req = pack('>2HL', SEARCHD_COMMAND_SEARCH, VER_COMMAND_SEARCH, length)+req
		sock.send(req)
		response = self._get_response(sock, VER_COMMAND_SEARCH)
		if not response:
			return {}

		# parse response
		result = {}
		max_ = len(response)

		# read schema
		p = 0
		fields = []
		attrs = []

		nfields = unpack('>L', response[p:p+4])[0]
		p += 4
		while nfields > 0 and p < max_:
			nfields -= 1
			length = unpack('>L', response[p:p+4])[0]
			p += 4
			fields.append(response[p:p+length])
			p += length

		nattrs = unpack('>L', response[p:p+4])[0]
		p += 4
		while nattrs>0 and p<max_:
			nattrs -= 1
			length = unpack('>L', response[p:p+4])[0]
			p += 4
			attr = response[p:p+length]
			p += length
			type_ = unpack('>L', response[p:p+4])[0]
			p += 4
			attrs.append(attr)

		# read match count
		count = unpack('>L', response[p:p+4])[0]
		p += 4

		# read matches
		results = {}
		results['attrs'] = attrs
		results['matches'] = []
		while count>0 and p<max_:
			count -= 1
			doc, weight = unpack('>2L', response[p:p+8])
			match = {
				'doc': doc,
				'weight': weight,
				'attrs': {},
			}
			#p += 8+(len(attrs)*4)
			p += 8
			for i in range(len(attrs)):
				match['attrs'][i] = unpack('>L', response[p:p+4])[0]
				p += 4
			results['matches'].append(match)
		results['total'], results['total_found'], results['time'], words = \
			unpack('>4L', response[p:p+16])
		results['time'] = '%.3f' % (results['time']/1000.0)
		sock.close()
		return results

	def extra(self, **kwargs):
		self._extra.update(**kwargs)
		return self

	def count(self):
		return self._get_sphinx_results()['total_found']

	def _get_results(self):
		results = self._get_sphinx_results()
		if results['matches'] and self._model:
			qs = self._model.objects.filter(pk__in=[r['doc'] for r in results['matches']])
			if self._select_related:
				qs = qs.select_related(*self._select_related_fields, **self._select_related_args)
			if self._extra:
				qs = qs.extra(**self._extra)
			queryset = dict([(o.id, o) for o in qs])
			results = [queryset[k['doc']] for k in results['matches'] if k['doc'] in queryset]
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
