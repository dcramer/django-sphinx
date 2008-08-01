from django.core.management.base import AppCommand
from django.db import models

from djangosphinx import SphinxSearch

class Command(AppCommand):
    help = "Prints generic configuration for any models which use a standard SphinxSearch manager."

    output_transaction = True

    def handle_app(self, app, **options):
        from djangosphinx.utils.config import generate_config_for_model
        model_classes = [getattr(app, n) for n in dir(app) if hasattr(getattr(app, n), '_meta')]
        found = 0
        for model in model_classes:
            done = False
            for n in dir(model):
                if done: continue
                try:
                    n = getattr(model, n)
                except:
                    continue
                if isinstance(n, SphinxSearch):
                    if n._index == model._meta.db_table:
                        found += 1
                        print generate_config_for_model(model)
                        done = True
        if found == 0:
            print "Unable to find any models in application which use standard SphinxSearch configuration."
        #return u'\n'.join(sql_create(app, self.style)).encode('utf-8')
