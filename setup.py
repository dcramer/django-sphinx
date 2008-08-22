#!/usr/bin/env python

from distutils.core import setup

setup(
    name='djangosphinx',
    version='2.0',
    author='David Cramer',
    author_email='dcramer@gmail.com',
    url='http://code.google.com/p/django-sphinx/',
    description = 'An integration layer bringing Django and Sphinx Search together.',
    packages = ['djangosphinx', 'djangosphinx.apis', 'djangosphinx.apis.api263', 'djangosphinx.apis.api275', 'djangosphinx.management', 'djangosphinx.management.commands', 'djangosphinx.utils'],
    package_data={'djangosphinx': ['templates/*']},
)
