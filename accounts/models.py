import secrets
import string

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django_countries.fields import CountryField


def generate_account_number():
    digits = ''.join(secrets.choice(string.digits) for _ in range(10))
    return f'NPB{digits}'


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('An email address is required.')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField('email address', unique=True)
    phone = models.CharField('phone number', max_length=20)
    country = CountryField('country of residence')
    account_number = models.CharField(
        'account number',
        max_length=13,
        unique=True,
        editable=False,
        blank=True,
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    objects = UserManager()

    class Meta:
        verbose_name = 'customer'
        verbose_name_plural = 'customers'

    def __str__(self):
        return self.get_full_name() or self.email

    def save(self, *args, **kwargs):
        if not self.account_number:
            for _ in range(10):
                candidate = generate_account_number()
                if not User.objects.filter(account_number=candidate).exists():
                    self.account_number = candidate
                    break
        super().save(*args, **kwargs)
