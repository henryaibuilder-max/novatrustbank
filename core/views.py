from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .legal_content import CAREERS_PAGE, PRIVACY_PAGE, TERMS_PAGE
from .service_content import SERVICE_PAGES


def _render_service(request, key):
    return render(request, 'core/services/page.html', {'page': SERVICE_PAGES[key]})


def home(request):
    context = {
        # Hero transactions (optional — template falls back to static HTML if empty)
        'hero_transactions': [],

        # Services (optional — template falls back to static HTML if empty)
        'services': [],
    }
    return render(request, 'core/home.html', context)


def about(request):
    return render(request, 'core/about.html')


def contact(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        message = request.POST.get('message', '').strip()

        if name and email and message:
            messages.success(
                request,
                'Thank you for reaching out. A member of our team will respond within 24 hours.',
            )
            return redirect('core:contact')

        messages.error(request, 'Please fill in all required fields.')

    return render(request, 'core/contact.html')

def personal_banking(request):
    return _render_service(request, 'personal_banking')


def business_banking(request):
    return _render_service(request, 'business_banking')


def loans_credit(request):
    return _render_service(request, 'loans_credit')


def cards(request):
    return _render_service(request, 'cards')


def grants_aid(request):
    return _render_service(request, 'grants_aid')


def careers(request):
    return render(request, 'core/careers.html', {'page': CAREERS_PAGE})


def privacy_policy(request):
    return render(request, 'core/legal/page.html', {'page': PRIVACY_PAGE})


def terms_of_service(request):
    return render(request, 'core/legal/page.html', {'page': TERMS_PAGE})