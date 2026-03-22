from django.apps import AppConfig

class SenmiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'senmi'

    def ready(self):
        import senmi.signals