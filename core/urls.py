from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('services/personal-banking/', views.personal_banking, name='personal_banking'),
    path('services/business-banking/', views.business_banking, name='business_banking'),
    path('services/loans-credit/', views.loans_credit, name='loans_credit'),
    path('services/cards/', views.cards, name='cards'),
    path('services/grants-aid/', views.grants_aid, name='grants_aid'),
    path('careers/', views.careers, name='careers'),
    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
    path('terms-of-service/', views.terms_of_service, name='terms_of_service'),
]