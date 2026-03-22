from django.db import models


#Create Rider Model with Images

class Rider(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15, unique=True)
    vehicle_type = models.CharField(max_length=50)
    vehicle_number = models.CharField(max_length=20)
    bank_account = models.CharField(max_length=50)
    
    # Images
    profile_picture = models.ImageField(upload_to='riders/profile/')
    bike_picture = models.ImageField(upload_to='riders/bike/')
    rider_with_bike_picture = models.ImageField(upload_to='riders/with_bike/')

    commission_percent = models.DecimalField(max_digits=5, decimal_places=2, default=20)

    def __str__(self):
        return self.name