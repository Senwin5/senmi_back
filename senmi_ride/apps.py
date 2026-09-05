from django.apps import AppConfig


class SenmiRideConfig(AppConfig):

    name = 'senmi_ride'

    def ready(self):
        import senmi_ride.signals