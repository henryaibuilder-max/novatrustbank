import re

from django import forms
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField

PHONE_PATTERN = re.compile(r'^\+?[\d\s\-\(\)]{7,20}$')


class BankSignupForm(forms.Form):
    first_name = forms.CharField(
        label=_('First name'),
        max_length=150,
        widget=forms.TextInput(attrs={
            'placeholder': 'Jane',
            'autocomplete': 'given-name',
        }),
    )
    last_name = forms.CharField(
        label=_('Last name'),
        max_length=150,
        widget=forms.TextInput(attrs={
            'placeholder': 'Smith',
            'autocomplete': 'family-name',
        }),
    )
    phone = forms.CharField(
        label=_('Phone number'),
        max_length=20,
        widget=forms.TelInput(attrs={
            'placeholder': '+1 (555) 123-4567',
            'autocomplete': 'tel',
        }),
    )
    country = CountryField().formfield(
        label=_('Country of residence'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    agree_terms = forms.BooleanField(
        label=_(
            'I agree to the Terms of Service and Privacy Policy, and confirm '
            'that the information provided is accurate.'
        ),
        required=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if 'password1' in self.fields:
            self.fields['password1'].help_text = None

        if 'password2' in self.fields:
            self.fields['password2'].help_text = None

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if not PHONE_PATTERN.match(phone):
            raise forms.ValidationError(
                _('Enter a valid phone number (7–20 digits, may include +, spaces, or dashes).')
            )
        return phone

    def signup(self, request, user):
        user.phone = self.cleaned_data['phone']
        user.country = self.cleaned_data['country']
        user.save(update_fields=['phone', 'country'])