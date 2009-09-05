#!/usr/bin/env python

from setuptools import setup, find_packages

from djangosphinx import version

setup(
    name='django-sphinx',
    version=".".join(map(str, version.__version__)),
    author='David Cramer',
    author_email='dcramer@gmail.com',
    url='http://github.com/dcramer/django-sphinx',
    install_requires=['django'],
    description = 'An integration layer bringing Django and Sphinx Search together.',
    packages=find_packages(),
    include_package_data=True,
)
