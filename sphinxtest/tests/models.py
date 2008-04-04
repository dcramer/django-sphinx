from django.db import models

from djangosphinx import SphinxSearch

import datetime

class Group(models.Model):
    name = models.CharField(max_length=32)

class Document(models.Model):
    group       = models.ForeignKey(Group)
    date_added  = models.DateTimeField(default=datetime.datetime.now)
    title       = models.CharField(max_length=32)
    content     = models.TextField()
    
    search      = SphinxSearch(index="test")
    
    class Meta:
        db_table = 'documents'