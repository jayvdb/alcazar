#!/usr/bin/env python
# -*- coding: utf-8 -*-

# We have a few methods in here whose exact signature varies from class to class -- pylint: disable=arguments-differ
# Also we access husker._value all over, the name starts with an underscores but that's ok, pylint: disable=protected-access

#----------------------------------------------------------------------------------------------------------------------------------
# includes

# 2+3 compat
from __future__ import absolute_import, division, print_function, unicode_literals

# standards
from datetime import datetime
from decimal import Decimal

# alcazar
from ..utils.compatibility import PY2
from .exceptions import HuskerLookupError, HuskerMismatch, HuskerMultipleSpecMatch, HuskerNotUnique

#----------------------------------------------------------------------------------------------------------------------------------
# globals

_builtin_int = int # pylint: disable=invalid-name
_unspecified = object() # pylint: disable=invalid-name

#----------------------------------------------------------------------------------------------------------------------------------

class SelectorMixin(object):
    # This could as well be part of `Husker`, it's separated only for readability and an aesthetic separation of concerns

    @property
    def id(self):
        return self.__class__.__name__

    def __call__(self, *args, **kwargs):
        return self.one(*args, **kwargs)

    def selection(self, *spec):
        """
        Runs a search for the given spec, and returns the results, as a ListHusker
        """
        raise NotImplementedError

    def parts(self, **fields):
        for key, husker in fields.items():
            if not isinstance(husker, Husker):
                husker = self.one(husker)
            yield key, husker

    def one(self, *spec):
        selected = self.selection(*spec)
        if len(selected) == 0:
            raise HuskerMismatch('%s found no matches for %s in %s' % (self.id, self.repr_spec(*spec), self.repr_value()))
        elif len(selected) > 1:
            raise HuskerNotUnique('%s expected 1 match for %s, found %d' % (self.id, self.repr_spec(*spec), len(selected)))
        else:
            return selected[0]

    def some(self, *spec):
        selected = self.selection(*spec)
        if len(selected) == 0:
            return NULL_HUSKER
        elif len(selected) > 1:
            raise HuskerNotUnique('%s expected 1 match for %s, found %d' % (self.id, self.repr_spec(*spec), len(selected)))
        else:
            return selected[0]

    def first(self, *spec):
        selected = self.selection(*spec)
        if len(selected) == 0:
            raise HuskerMismatch('%s found no matches for %s in %s' % (self.id, self.repr_spec(*spec), self.repr_value()))
        else:
            return selected[0]

    def last(self, *spec):
        selected = self.selection(*spec)
        if len(selected) == 0:
            raise HuskerMismatch('%s found no matches for %s in %s' % (self.id, self.repr_spec(*spec), self.repr_value()))
        else:
            return selected[-1]

    def any(self, *spec):
        selected = self.selection(*spec)
        if len(selected) == 0:
            return NULL_HUSKER
        else:
            return selected[0]

    def all(self, *spec):
        selected = self.selection(*spec)
        if not selected:
            raise HuskerMismatch('%s found no matches for %s in %s' % (self.id, self.repr_spec(*spec), self.repr_value()))
        return selected

    def one_of(self, *all_specs):
        match = self.some_of(*all_specs)
        if not match:
            raise HuskerMismatch("%s: none of the specified specs matched %r: %s" % (
                self.id,
                self._value,
                ', '.join('"%s"' % spec for spec in all_specs),
            ))
        return match

    def some_of(self, *all_specs):
        match = matching_spec = None
        for spec in all_specs:
            if not isinstance(spec, (list, tuple)):
                spec = [spec]
            selected = self.some(*spec)
            if selected:
                if matching_spec is None:
                    match, matching_spec = selected, spec
                else:
                    raise HuskerMultipleSpecMatch('%s: both %s and %s matched' % (
                        self.id,
                        self.repr_spec(*matching_spec),
                        self.repr_spec(*spec),
                    ))
        return match

    def first_of(self, *all_specs):
        for spec in all_specs:
            if not isinstance(spec, (list, tuple)):
                spec = [spec]
            selected = self.any(*spec)
            if selected:
                return selected
        raise HuskerMismatch("%s: none of the specified specs matched: %s" % (
            self.id,
            ', '.join('"%s"' % spec for spec in all_specs),
        ))

    def any_of(self, *all_specs):
        for spec in all_specs:
            if not isinstance(spec, (list, tuple)):
                spec = [spec]
            selected = self.any(*spec)
            if selected:
                return selected
        return NULL_HUSKER

    def all_of(self, *all_specs):
        return ListHusker(
            element
            for spec in all_specs
            for element in self.all(spec)
        )

    def selection_of(self, *all_specs):
        return ListHusker(
            element
            for spec in all_specs
            for element in self.selection(spec)
        )

#----------------------------------------------------------------------------------------------------------------------------------
# utils

def _forward_to_value(method_name, return_type):
    def method(self, *args, **kwargs):
        wrapped = getattr(self._value, method_name, None)
        if not callable(wrapped):
            raise NotImplementedError((self.__class__.__name__, self._value.__class__.__name__, method_name))
        raw = wrapped(*args, **kwargs)
        if raw is NotImplemented:
            return NotImplemented
        return return_type(raw)
    return method

#----------------------------------------------------------------------------------------------------------------------------------

class Husker(SelectorMixin):
    """
    A Husker is used to extract from a raw document those bits of data that are of relevance to our scraper. It does not concern
    itself with cleaning or converting that data -- that's for the `Cleaner` to do. A Husker is just about locating the document
    node, or the text substring, that we're looking for.
    """

    def __init__(self, value):
        self._value = value

    @property
    def text(self):
        """
        Returns a TextHusker, whose value is this husker's text contents. The definition of what constitutes "this husker's text
        contents" is up to the implementing subclass.
        """
        raise NotImplementedError(repr(self))

    @property
    def multiline(self):
        """ Same as `text`, but preserves line breaks """
        raise NotImplementedError(repr(self))

    @property
    def str(self):
        return self.text._value

    @property
    def int(self):
        return int(self.str)

    @property
    def float(self):
        return float(self.str)

    @property
    def decimal(self):
        return Decimal(self.str)

    def date(self, fmt='%Y-%m-%d'):
        return datetime.strptime(self.str, fmt).date()

    def datetime(self, fmt='%Y-%m-%dT%H:%M:%S'):
        text = self.text.sub(
            r'(?:\.\d+|[\+\-]\d\d?(?::\d\d?)?|Z)*$',
            '',
        )
        return datetime.strptime(text.str, fmt)

    # NB method `json` is moneky-patched into here from JmesPathHusker

    def map_raw(self, function):
        return function(self.raw)

    def map(self, function):
        return function(self)

    def filter(self, function):
        if function(self):
            return self
        else:
            return NULL_HUSKER

    def lookup(self, table, default=_unspecified):
        try:
            return table[self.str]
        except KeyError:
            if default is _unspecified:
                raise HuskerLookupError(repr(self.raw))
            else:
                return default

    @property
    def raw(self):
        # In the default case, return ._value, but some subclasses override this
        return self._value

    def __bool__(self):
        """
        A husker evaluates as truthy iff it holds a value at all, irrespective of what that value's truthiness is.
        """
        return self._value is not None

    if PY2:
        # NB don't just say `__nonzero__ = __bool__` because `__bool__` is overriden in some subclasses
        def __nonzero__(self):
            return self.__bool__()

    def repr_spec(self, *spec):
        if len(spec) == 1:
            return repr(spec[0])
        else:
            return repr(spec)

    def repr_value(self):
        return repr(self.text._value)

    def __str__(self):
        return self.text._value

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self._value)

    __hash__ = _forward_to_value('__hash__', _builtin_int)
    __eq__ = _forward_to_value('__eq__', bool)
    __ne__ = _forward_to_value('__ne__', bool)
    __lt__ = _forward_to_value('__lt__', bool)
    __le__ = _forward_to_value('__le__', bool)
    __gt__ = _forward_to_value('__gt__', bool)
    __ge__ = _forward_to_value('__ge__', bool)

#----------------------------------------------------------------------------------------------------------------------------------

class ListHusker(Husker):

    def __init__(self, value):
        assert value is not None
        if not callable(getattr(value, '__len__', None)):
            value = list(value)
        super(ListHusker, self).__init__(value)

    def __iter__(self):
        return iter(self._value)

    def __len__(self):
        return len(self._value)

    def __getitem__(self, item):
        return self._value[item]

    def __bool__(self):
        return bool(self._value)

    def __add__(self, other):
        return ListHusker(self._value + other._value)

    def selection(self, test=None):
        if test is not None and not callable(test):
            spec = test
            test = lambda child: child.selection(spec)
        return ListHusker(
            child
            for child in self._value
            if test is None or test(child)
        )

    def dedup(self, key=None):
        seen = set()
        deduped = []
        for child in self._value:
            keyed = child if key is None else key(child)
            if keyed not in seen:
                seen.add(keyed)
                deduped.append(child)
        return ListHusker(deduped)

    def _mapped_property(name, cls=None): # pylint: disable=no-self-argument
        return property(lambda self: (cls or self.__class__)(
            getattr(child, name)
            for child in self._value
        ))

    def _mapped_operation(name, cls=None): # pylint: disable=no-self-argument
        def operation(self, *args, **kwargs):
            list_cls = cls or self.__class__
            return list_cls(
                getattr(child, name)(*args, **kwargs)
                for child in self._value
            )
        return operation

    text = _mapped_property('text')
    multiline = _mapped_property('multiline')
    js = _mapped_operation('js')
    json = _mapped_operation('json')
    sub = _mapped_operation('sub')
    attrib = _mapped_operation('attrib')
    raw = _mapped_property('raw', cls=list)
    str = _mapped_property('str', cls=list)
    int = _mapped_property('int', cls=list)
    float = _mapped_property('float', cls=list)
    date = _mapped_operation('date', cls=list)
    datetime = _mapped_operation('datetime', cls=list)

    def map_raw(self, function):
        return [function(element.raw) for element in self]

    def map(self, function):
        return [function(element) for element in self]

    def filter(self, function):
        return ListHusker(
            element
            for element in self
            if function(element)
        )

    def __str__(self):
        return repr(self._value)


EMPTY_LIST_HUSKER = ListHusker([])

#----------------------------------------------------------------------------------------------------------------------------------

class NullHusker(Husker):

    def __init__(self):
        super(NullHusker, self).__init__(None)

    _returns_null = lambda *args, **kwargs: NULL_HUSKER
    _returns_none = lambda *args, **kwargs: None

    selection = _returns_null
    one = _returns_null
    some = _returns_null
    first = _returns_null
    last = _returns_null
    any = _returns_null
    all = _returns_null
    one_of = _returns_null
    some_of = _returns_null
    first_of = _returns_null
    any_of = _returns_null
    all_of = _returns_null
    selection_of = _returns_null

    text = property(_returns_null)
    multiline = property(_returns_null)
    join = _returns_null
    list = _returns_null
    sub = _returns_null
    lower = _returns_null
    upper = _returns_null

    __getitem__ = _returns_null
    attrib = _returns_null

    json = _returns_null
    str = property(_returns_none)
    int = property(_returns_none)
    float = property(_returns_none)
    date = _returns_none
    datetime = _returns_none

    map = _returns_null
    map_raw = _returns_none
    filter = _returns_null
    lookup = _returns_none

    __eq__ = lambda self, other: other is None
    __ne__ = lambda self, other: other is not None
    __lt__ = lambda self, other: False
    __le__ = lambda self, other: False
    __gt__ = lambda self, other: False
    __ge__ = lambda self, other: False

    def __str__(self):
        return '<Null>'


NULL_HUSKER = NullHusker()

#----------------------------------------------------------------------------------------------------------------------------------