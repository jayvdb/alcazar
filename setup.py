#!/usr/bin/env python

#----------------------------------------------------------------------------------------------------------------------------------

# 2+3 compatibility
from __future__ import unicode_literals

# standards
from os import path
import re
import setuptools

#----------------------------------------------------------------------------------------------------------------------------------

with open(path.join(path.dirname(__file__), 'README.md'), 'rb') as file_in:
    long_description = file_in.read().decode('UTF-8')

with open(path.join(path.dirname(__file__), 'alcazar', 'version.py'), 'rb') as file_in:
    alcazar_version = re.search(
        r'ALCAZAR_VERSION = \'(.+)\'',
        file_in.read().decode('UTF-8'),
    ).group(1)

setuptools.setup(
    name='alcazar',
    version=alcazar_version,
    author='Herv\u00e9 Saint-Amand',
    author_email='alcazar@saintamh.org',
    description='Web scraper framework',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/saintamh/alcazar/',
    packages=setuptools.find_packages(exclude=["tests", "tests.*"]),
    entry_points={
        'console_scripts': [
            'alcazar = alcazar.cli:main',
            'bodytext = alcazar.bodytext:main',
        ],
    },
    install_requires=[
        'lxml>=4,<5',
        'cssselect>=1.0,<2',
        'jmespath>=0.9.3,<1',
        'requests>=2,<3',
        'urllib3>=1.17,<2',
    ],
    classifiers=[
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Topic :: Internet :: WWW/HTTP :: Indexing/Search',
        'Topic :: Software Development :: Libraries',
    ],
)

#----------------------------------------------------------------------------------------------------------------------------------
