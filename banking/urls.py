from django.urls import path
from . import views

app_name = 'banking'

urlpatterns = [
    # ... (Keep dashboard, transactions, and functional view configurations unchanged) ...
    path('', views.dashboard, name='dashboard'),
    path('transactions/',         views.transactions,            name='transactions'),
    path('cards/',                views.cards,                   name='cards'),
    path('transfer/local/',       views.local_transfer,          name='local_transfer'),
    path('transfer/international/', views.international_transfer, name='international_transfer'),
    path('deposit/',              views.deposit,                 name='deposit'),
    path('currency-swap/',        views.currency_swap,           name='currency_swap'),
    path('loans/',                views.loans,                   name='loans'),
    path('pay-bills/',            views.pay_bills,               name='pay_bills'),
    
    # Global Verification & Support Escalation Routes
    path('support/dispatch/',     views.submit_action_to_support, name='submit_action_to_support'),
    path('support/tickets/',      views.support_chat_list,       name='support_chat_list'),
    path('support/ticket/<str:support_id>/', views.support_chat_detail, name='support_chat_detail'),

    path('dashboard/support/poll/<str:support_id>/', views.poll_chat_messages, name='poll_chat_messages'),
    path('dashboard/support/send/<str:support_id>/', views.send_chat_message, name='send_chat_message'),
]