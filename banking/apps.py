from django.apps import AppConfig


class BankingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'banking'

    def ready(self):
        # Auto-create Account when a new User is saved.
        from django.db.models.signals import post_save
        from django.conf import settings
        from .models import Account

        def create_account(sender, instance, created, **kwargs):
            if created:
                Account.objects.get_or_create(user=instance)

        post_save.connect(create_account, sender=settings.AUTH_USER_MODEL)