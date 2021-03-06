#!/usr/bin/env python
# -*- coding: utf-8 -*-

#----------------------------------------------------------------------------------------------------------------------------------
# includes

# 2+3 compat
from __future__ import absolute_import, division, print_function, unicode_literals

# standards
from types import GeneratorType

# alcazar
from ..utils.compatibility import integer_types, text_type
from .base import Husker, ListHusker, NULL_HUSKER, NullHusker, ScalarHusker, TextHusker
from .element import ElementHusker
from .exceptions import (
    HuskerError, HuskerAttributeNotFound, HuskerMismatch, HuskerNotUnique, HuskerMultipleSpecMatch, HuskerLookupError,
    HuskerValueError,
)
from .jmespath import JmesPathHusker

#----------------------------------------------------------------------------------------------------------------------------------

def husk(value):
    if isinstance(value, Husker):
        return value
    elif isinstance(value, text_type):
        return TextHusker(value)
    elif isinstance(value, integer_types + (float, bool)):
        return ScalarHusker(value)
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
