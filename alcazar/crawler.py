#!/usr/bin/env python
# -*- coding: utf-8 -*-

#----------------------------------------------------------------------------------------------------------------------------------
# includes

# 2+3 compat
from __future__ import absolute_import, division, print_function, unicode_literals

# 3rd parties
import requests

# alcazar
from .exceptions import SkipThisPage
from .husker import TextHusker
from .scraper import Scraper

#----------------------------------------------------------------------------------------------------------------------------------
# scheduler

class Scheduler(object):
    """
    Every crawler uses a Scheduler, which stores and sorts the Query objects to be fetched
    """

    def add(self, query):
        raise NotImplementedError

    def add_all(self, queries):
        for query in queries:
            self.add(query)

    def pop(self):
        raise NotImplementedError

    def __len__(self):
        raise NotImplementedError

    @property
    def empty(self):
        return len(self) == 0


class StackScheduler(Scheduler):
    """
    Very simple in-memory query scheduler. Pages are visited depth-first, i.e. LIFO, and the links extracted from any one given
    page are popped off the stack in the same order that they appear on the page.
    """

    def __init__(self):
        self.stack = []

    def add(self, query):
        self.stack.append(query)

    def add_all(self, queries):
        super(StackScheduler, self).add_all(reversed(queries))

    def pop(self):
        return self.stack.pop()

    def __len__(self):
        return len(self.stack)

#----------------------------------------------------------------------------------------------------------------------------------

class Crawler(Scraper):
    """
    A `Crawler` is a scraper that issues multiple requests, where the list of requests ultimately made depends on the data and
    isn't fully pre-programmed.
    """

    def __init__(self, scheduler=None, **kwargs):
        # NB this class saves some state on `self', so it is not thread-safe. When building a multithreaded crawler, each thread
        # must instantiate its own Crawler, and they can all share the same scheduler (or they can use a Scheduler implementation
        # that reads from a central database).
        super(Crawler, self).__init__(**kwargs)
        self.scheduler = scheduler or StackScheduler()

    def crawl(self):
        while not scheduler.empty:
            query = scheduler.pop()
            try:
                self.scrape(query)
            except SkipThisPage as reason:
                self.log_skipped_page(query, reason)

    def enqueue(self, request, **kwargs):
        request = self.compile_request(request, self.current_referer)
        methods, rest = self.compile_method_pointers(**kwargs)
        self.current_link_batch.append(Query(
            request=request,
            methods=methods,
            extras=self.compile_extras(forward_extras, rest),
        ))

    def log_skipped_page(self, query, reason):
        logging.info("Skipped %s (%s)", query, reason)

#----------------------------------------------------------------------------------------------------------------------------------
