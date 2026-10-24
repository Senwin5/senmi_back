from rest_framework.permissions import BasePermission


class IsRideAdmin(BasePermission):
    """
    Only authenticated Django staff or superuser accounts
    can access Ride notification administration.
    """

    def has_permission(self, request, view):
        user = request.user

        return bool(
            user
            and user.is_authenticated
            and (user.is_staff or user.is_superuser)
        )