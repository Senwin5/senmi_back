# senmi/admin.py
from django.contrib import admin
from .models import User, RiderProfile

# -----------------------------
# Customize User admin
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('id', 'email', 'username', 'role', 'is_staff', 'is_active')
    list_filter = ('role', 'is_staff', 'is_active')
    search_fields = ('email', 'username')
    ordering = ('id',)
    readonly_fields = ('id',)

# -----------------------------
# Customize RiderProfile admin
@admin.register(RiderProfile)
class RiderProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'full_name', 'phone_number', 'status', 'rejection_reason')
    list_filter = ('status',)
    search_fields = ('user__email', 'full_name', 'phone_number')
    ordering = ('id',)
    readonly_fields = ('id',)