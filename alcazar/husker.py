#!/usr/bin/env python
# -*- coding: utf-8 -*-

# We have a few methods in here whose exact signature varies from class to class -- pylint: disable=arguments-differ
# Also we access ._value and ET._Comment, even though their names start with underscores -- pylint: disable=protected-access

#----------------------------------------------------------------------------------------------------------------------------------
# includes

# 2+3 compat
from __future__ import absolute_import, division, print_function, unicode_literals

# standards
from datetime import datetime
from decimal import Decimal
from functools import reduce
import json
import operator
import re
from types import GeneratorType

# 3rd parties
import jmespath
import lxml.etree as ET
try:
    from lxml.cssselect import CSSSelector
except ImportError:
    CSSSelector = NotImplemented # pylint: disable=invalid-name

# alcazar
from .exceptions import ScraperError
from .utils.compatibility import PY2, bytes_type, string_types, text_type, unescape_html
from .utils.etree import detach_node
from .utils.jsonutils import lenient_json_loads, strip_js_comments
from .utils.text import normalize_spaces

#----------------------------------------------------------------------------------------------------------------------------------
# globals

_builtin_int = int # pylint: disable=invalid-name
_unspecified = object() # pylint: disable=invalid-name

#----------------------------------------------------------------------------------------------------------------------------------
# exceptions

class HuskerError(ScraperError):
    pass

class HuskerAttributeNotFound(HuskerError):
    pass

class HuskerMismatch(HuskerError):
    pass

class HuskerNotUnique(HuskerError):
    pass

class HuskerMultipleSpecMatch(HuskerNotUnique):
    pass

class HuskerLookupError(HuskerError):
    pass

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
        if return_type is text_type:
            convert = TextHusker
        elif return_type is list:
            convert = lambda values: ListHusker(map(TextHusker, values))
        else:
            convert = return_type
        wrapped = getattr(self._value, method_name, None)
        if callable(wrapped):
            raw = wrapped(*args, **kwargs)
            if raw is NotImplemented:
                return raw
            return convert(raw)
        else:
            raise NotImplementedError((self.__class__.__name__, self._value.__class__.__name__, method_name))
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

    def json(self):
        return JmesPathHusker(lenient_json_loads(self.str))

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

class ElementHusker(Husker):

    def __init__(self, value, is_full_document=False):
        assert value is not None
        super(ElementHusker, self).__init__(value)
        self.is_full_document = is_full_document

    def __iter__(self):
        for child in self._value:
            yield ElementHusker(child)

    def __len__(self):
        return len(self._value)

    def __getitem__(self, item):
        value = self._value.attrib.get(item, _unspecified)
        if value is _unspecified:
            raise HuskerAttributeNotFound(repr(item))
        return TextHusker(unescape_html(self._ensure_decoded(value)))

    def attrib(self, item, default=NULL_HUSKER):
        value = self._value.attrib.get(item, _unspecified)
        if value is _unspecified:
            return default
        return TextHusker(unescape_html(self._ensure_decoded(value)))

    @property
    def children(self):
        return ListHusker(map(ElementHusker, self._value))

    def descendants(self):
        for descendant in self._value.iter():
            yield ElementHusker(descendant)

    def selection(self, path):
        xpath = self._compile_xpath(path)
        selected = ET.XPath(
            xpath,
            # you can use regexes in your paths, e.g. '//a[re:test(text(),"reg(?:ular)?","i")]'
            namespaces={'re':'http://exslt.org/regular-expressions'},
        )(self._value)
        return ListHusker(
            husk(self._ensure_decoded(v))
            for v in selected
        )

    def _compile_xpath(self, path):
        if re.search(r'(?:^\.(?=/)|/|@|^\w+$)', path):
            return re.sub(
                r'^(\.?)(/{,2})',
                lambda m: '%s%s' % (
                    m.group(1) if self.is_full_document else '.',
                    m.group(2) or '//',
                ),
                path
            )
        else:
            return self._css_path_to_xpath(path)

    @staticmethod
    def _ensure_decoded(value):
        # lxml returns bytes when the data is ASCII, even when the input was text, which feels wrong but hey
        if isinstance(value, bytes_type):
            value = value.decode('us-ascii')
        return value

    @property
    def text(self):
        return TextHusker(normalize_spaces(''.join(self._value.itertext())))

    @property
    def multiline(self):
        return TextHusker(self._multiline_text())

    def _multiline_text(self):
        def visit(node, inside_pre=False):
            if node.tag == 'pre':
                inside_pre = True
            if node.tag == 'br':
                yield "\n"
            elif node.tag in self._PARAGRAPH_BREAKING_TAGS:
                yield "\n\n"
            if node.tag not in self._NON_TEXT_TAGS and not isinstance(node, ET._Comment):
                if node.text:
                    yield node.text if inside_pre else normalize_spaces(node.text)
                for child in node:
                    for value in visit(child, inside_pre):
                        yield value
            if node.tag in self._PARAGRAPH_BREAKING_TAGS:
                yield "\n\n"
            if node.tail:
                yield node.tail if inside_pre else normalize_spaces(node.tail)
        return re.sub(
            r'\s+',
            lambda m: "\n\n" if "\n\n" in m.group() else "\n" if "\n" in m.group() else " ",
            ''.join(visit(self._value)),
        ).strip()

    @property
    def head(self):
        return husk(self._ensure_decoded(self._value.text))

    @property
    def tail(self):
        return husk(self._ensure_decoded(self._value.tail))

    @property
    def next(self):
        return husk(self._value.getnext())

    @property
    def previous(self):
        return husk(self._value.getprevious())

    @property
    def parent(self):
        return husk(self._value.getparent())

    @property
    def tag(self):
        return TextHusker(self._ensure_decoded(self._value.tag))

    def js(self, strip_comments=True):
        js = "\n".join(
            re.sub(r'^\s*<!--', '', re.sub(r'-->\s*$', '', js_text))
            for js_text in self._value.xpath('.//script/text()')
        )
        if strip_comments:
            js = strip_js_comments(js)
        return TextHusker(js)

    def detach(self, reattach_tail=True):
        detach_node(self._value, reattach_tail=reattach_tail)

    def repr_spec(self, path):
        return "'%s'" % path

    def repr_value(self, max_width=200, max_lines=100, min_trim=10):
        source_text = self.html_source()
        source_text = re.sub(r'(?<=.{%d}).+' % max_width, u'\u2026', source_text)
        lines = source_text.split('\n')
        if len(lines) >= max_lines + min_trim:
            lines = lines[:max_lines//2] \
                + ['', u'    [\u2026 %d lines snipped \u2026]' % (len(lines) - max_lines), ''] \
                + lines[-max_lines//2:]
            source_text = '\n'.join(lines)
        return 'etree:\n\n%s\n%s\n%s\n' % (
            '-' * max_width,
            source_text.strip(),
            '-' * max_width,
        )

    def html_source(self):
        return ET.tostring(
            self._value,
            pretty_print=True,
            method='HTML',
            encoding=text_type,
        )

    @staticmethod
    def _css_path_to_xpath(path):
        if CSSSelector is NotImplemented:
            raise NotImplementedError("lxml.cssselect module not found")
        return CSSSelector(path).path

    _PARAGRAPH_BREAKING_TAGS = frozenset((
        'address', 'applet', 'blockquote', 'body', 'center', 'cite', 'dd', 'div', 'dl', 'dt', 'fieldset', 'form', 'frame',
        'frameset', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'head', 'hr', 'iframe', 'li', 'noscript', 'object', 'ol', 'p', 'table',
        'tbody', 'td', 'textarea', 'tfoot', 'th', 'thead', 'title', 'tr', 'ul',
    ))

    _NON_TEXT_TAGS = frozenset((
        'script', 'style',
    ))

#----------------------------------------------------------------------------------------------------------------------------------

class JmesPathHusker(Husker):

    @classmethod
    def _child(cls, value):
        if value is None:
            return NULL_HUSKER
        elif isinstance(value, str):
            return TextHusker(value)
        else:
            return JmesPathHusker(value)

    def selection(self, path):
        selected = jmespath.search(path, self._value)
        if '[' not in path:
            selected = [selected]
        return ListHusker(map(self._child, selected))

    @property
    def text(self):
        text = self._value
        if not isinstance(text, str):
            text = json.dumps(text, sort_keys=True)
        return TextHusker(text)

    @property
    def multiline(self):
        text = self._value
        if not isinstance(text, str):
            text = json.dumps(text, indent=4, sort_keys=True)
        return TextHusker(text)

    @property
    def list(self):
        if not isinstance(self._value, list):
            raise HuskerError("value is a %s, not a list" % self._value.__class__.__name__)
        return ListHusker(map(self._child, self._value))

    def __getitem__(self, item):
        return self.one(item)

#----------------------------------------------------------------------------------------------------------------------------------

class TextHusker(Husker):

    def __init__(self, value):
        assert value is not None
        super(TextHusker, self).__init__(value)

    def selection(self, regex, flags=''):
        regex = self._compile(regex, flags)
        selected = regex.finditer(self._value)
        if regex.groups < 2:
            return ListHusker(map(husk, (
                m.group(regex.groups)
                for m in selected
            )))
        else:
            return ListHusker(
                ListHusker(map(husk, m.groups()))
                for m in selected
            )

    def sub(self, regex, replacement, flags=''):
        return TextHusker(
            self._compile(regex, flags).sub(
                replacement,
                self._value,
            )
        )

    @property
    def text(self):
        return self

    @property
    def multiline(self):
        return self

    @property
    def normalized(self):
        return TextHusker(normalize_spaces(self._value))

    def lower(self):
        return TextHusker(self._value.lower())

    def upper(self):
        return TextHusker(self._value.upper())

    def repr_spec(self, regex, flags=''):
        return "%s%s" % (
            re.sub(r'^u?[\'\"](.*)[\'\"]$', r'/\1/', regex),
            flags,
        )

    def __add__(self, other):
        return TextHusker(self._value + other._value)

    def __bool__(self):
        return bool(self._value)

    def __str__(self):
        return self._value

    @staticmethod
    def _compile(regex, flags):
        if isinstance(regex, string_types):
            return re.compile(
                regex,
                reduce(
                    operator.or_,
                    (getattr(re, f.upper()) for f in flags),
                    0,
                ),
            )
        elif flags == '':
            return regex
        else:
            raise ValueError((regex, flags))

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

    def join(self, sep):
        return TextHusker(sep.join(e.str for e in self))

    def __str__(self):
        return repr(self._value)

EMPTY_LIST_HUSKER = ListHusker([])

#----------------------------------------------------------------------------------------------------------------------------------
# public utils

def husk(value):
    if isinstance(value, text_type):
        # NB this includes _ElementStringResult objects that lxml returns when your xpath ends in "/text()"
        return TextHusker(value)
    elif callable(getattr(value, 'xpath', None)):
        return ElementHusker(value)
    elif isinstance(value, (tuple, list, GeneratorType)):
        return ListHusker(value)
    elif value is None:
        return NULL_HUSKER
    else:
        # NB this includes undecoded bytes
        raise ValueError(repr(value))

#----------------------------------------------------------------------------------------------------------------------------------
