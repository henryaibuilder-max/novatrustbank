from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ('email',)
    list_display = (
        'email',
        'first_name',
        'last_name',
        'account_number',
        'country',
        'phone',
        'is_staff',
    )
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'country')
    search_fields = ('email', 'first_name', 'last_name', 'account_number', 'phone')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {
            'fields': ('first_name', 'last_name', 'phone', 'country', 'account_number'),
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'email',
                'first_name',
                'last_name',
                'phone',
                'country',
                'password1',
                'password2',
            ),
        }),
    )
