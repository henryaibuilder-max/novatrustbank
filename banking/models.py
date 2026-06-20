import secrets
import string
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django_countries.fields import CountryField

# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def generate_reference():
    """Unique transaction reference: TXN + 12 hex chars."""
    return 'TXN' + secrets.token_hex(6).upper()

def generate_otp():
    """Generates a secure, readable 6-digit numeric OTP string for support lookup."""
    return "".join(secrets.choice(string.digits) for _ in range(6))

def generate_support_id():
    """Generates a unique ticket identifier: TKT-XXXX-XXXX"""
    return 'TKT-' + secrets.token_hex(3).upper() + '-' + secrets.token_hex(3).upper()


# ─────────────────────────────────────────────
#  Account (Holds multi-currency/crypto balances)
# ─────────────────────────────────────────────

class Account(models.Model):
    CURRENCY_USD = 'USD'
    CURRENCY_EUR = 'EUR'
    CURRENCY_GBP = 'GBP'
    CURRENCY_NGN = 'NGN'

    CURRENCY_CHOICES = [
        (CURRENCY_USD, 'US Dollar ($)'),
        (CURRENCY_EUR, 'Euro (€)'),
        (CURRENCY_GBP, 'British Pound (£)'),
        (CURRENCY_NGN, 'Nigerian Naira (₦)'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='account',
    )
    balance = models.DecimalField(
        'fiat balance',
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        default=CURRENCY_USD,  # Updated default to USD
    )
    btc_balance = models.DecimalField(
        'bitcoin balance',
        max_digits=14,
        decimal_places=8,
        default=Decimal('0.00000000'),
    )
    daily_limit = models.DecimalField(
        'daily transfer limit',
        max_digits=14,
        decimal_places=2,
        default=Decimal('5000.00'),  # Adjusted standard USD limit
    )
    is_verified = models.BooleanField('KYC verified', default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'account'
        verbose_name_plural = 'accounts'

    def __str__(self):
        return f'{self.user} — {self.currency} {self.balance}'

    @property
    def total_portfolio(self):
        """Fiat balance only; extend when live BTC rate is wired in."""
        return self.balance


# ─────────────────────────────────────────────
#  Transaction Ledger
# ─────────────────────────────────────────────

class Transaction(models.Model):
    TYPE_CREDIT = 'credit'
    TYPE_DEBIT  = 'debit'
    TYPE_CHOICES = [
        (TYPE_CREDIT, 'Credit'),
        (TYPE_DEBIT,  'Debit'),
    ]

    STATUS_PENDING   = 'pending'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED    = 'failed'
    STATUS_REVERSED  = 'reversed'
    STATUS_CHOICES = [
        (STATUS_PENDING,   'Pending'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED,    'Failed'),
        (STATUS_REVERSED,  'Reversed'),
    ]

    CATEGORY_TRANSFER   = 'transfer'
    CATEGORY_DEPOSIT    = 'deposit'
    CATEGORY_WITHDRAWAL = 'withdrawal'
    CATEGORY_BILL       = 'bill_payment'
    CATEGORY_LOAN       = 'loan'
    CATEGORY_SWAP       = 'currency_swap'
    CATEGORY_CHOICES = [
        (CATEGORY_TRANSFER,   'Transfer'),
        (CATEGORY_DEPOSIT,    'Deposit'),
        (CATEGORY_WITHDRAWAL, 'Withdrawal'),
        (CATEGORY_BILL,       'Bill Payment'),
        (CATEGORY_LOAN,       'Loan'),
        (CATEGORY_SWAP,       'Currency Swap'),
    ]

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='transactions',
    )
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default=CATEGORY_TRANSFER,
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')  # Updated default to USD
    balance_after = models.DecimalField(
        'balance after transaction',
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    reference = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        default=generate_reference,
    )
    description = models.CharField(max_length=255, blank=True)
    counterpart_name = models.CharField(
        'recipient / sender name',
        max_length=255,
        blank=True,
    )
    counterpart_account = models.CharField(
        'recipient / sender account',
        max_length=50,
        blank=True,
    )
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'transaction'
        verbose_name_plural = 'transactions'

    def __str__(self):
        return f'{self.reference} | {self.type} ${self.amount}'


# ─────────────────────────────────────────────
#  Local Transfer (US Domestic ACH / Wire)
# ─────────────────────────────────────────────


class LocalTransfer(models.Model):
    # Account Type Choices
    TYPE_SAVINGS = 'savings'
    TYPE_CURRENT = 'current'
    TYPE_JOINT = 'joint'
    TYPE_CORPORATE = 'corporate'
    
    ACCOUNT_TYPE_CHOICES = [
        (TYPE_SAVINGS, 'Savings Account'),
        (TYPE_CURRENT, 'Current Account'),
        (TYPE_JOINT, 'Joint Account'),
        (TYPE_CORPORATE, 'Corporate Account'),
    ]

    STATUS_PENDING   = 'pending'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED    = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING,   'Pending (Awaiting Support OTP)'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED,    'Failed'),
    ]

    sender = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='outgoing_transfers',
    )
    
    # --- Exact Fields Collected from User Form ---
    recipient_name = models.CharField(
        'Account Holder Name', 
        max_length=255
    )
    recipient_account_number = models.CharField(
        'Account Number', 
        max_length=50
    )
    recipient_bank = models.CharField(
        'Bank Name', 
        max_length=255
    )
    account_type = models.CharField(
        'Account Type',
        max_length=20,
        choices=ACCOUNT_TYPE_CHOICES,
        help_text='Selected destination account type'
    )
    routing_number = models.CharField(
        'Routing Number', 
        max_length=9,
        help_text='9-digit number found on your checks'
    )
    swift_code = models.CharField(
        'SWIFT Code', 
        max_length=11, 
        blank=True,
        help_text='8–11 character bank identifier code'
    )
    
    # --- Operational Metadata ---
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    description = models.CharField(max_length=255, blank=True)
    reference = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        default=generate_reference,
    )
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    
    # --- Security/Support Validation Fields ---
    required_otp = models.CharField(
        'Support Generated OTP', 
        max_length=6, 
        default=generate_otp,
        help_text="To be provided to the customer by support team via chat."
    )
    is_otp_verified = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'local transfer'

    def __str__(self):
        return f'{self.reference} → {self.recipient_name} (${self.amount})'
    


# ─────────────────────────────────────────────
#  International Transfer
# ─────────────────────────────────────────────

class InternationalTransfer(models.Model):
    STATUS_PENDING    = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED  = 'completed'
    STATUS_FAILED     = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING,    'Pending (Awaiting Support OTP)'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_COMPLETED,  'Completed'),
        (STATUS_FAILED,     'Failed'),
    ]

    sender = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='international_transfers',
    )
    recipient_name = models.CharField(max_length=255)
    recipient_bank = models.CharField(max_length=255)
    recipient_account = models.CharField(max_length=50)
    recipient_country = CountryField('recipient country', default='US')  # Dynamic, defaulted to US
    swift_bic = models.CharField('SWIFT / BIC code', max_length=11, blank=True)
    iban = models.CharField('IBAN', max_length=34, blank=True)
    amount_sent = models.DecimalField(
        'amount (source currency)',
        max_digits=14,
        decimal_places=2,
    )
    source_currency = models.CharField(max_length=3, default='USD')  # Updated default to USD
    amount_received = models.DecimalField(
        'estimated received amount',
        max_digits=14,
        decimal_places=2,
    )
    target_currency = models.CharField(max_length=3, default='EUR')
    exchange_rate = models.DecimalField(max_digits=12, decimal_places=6)
    description = models.CharField(max_length=255, blank=True)
    reference = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        default=generate_reference,
    )
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    
    # --- Security/Support Validation Fields ---
    required_otp = models.CharField(
        'Support Generated OTP', 
        max_length=6, 
        default=generate_otp,
        help_text="To be provided to the customer by support team via chat."
    )
    is_otp_verified = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'international transfer'

    def __str__(self):
        return f'{self.reference} → {self.recipient_name} ({self.target_currency})'


# ─────────────────────────────────────────────
#  Bill Payment
# ─────────────────────────────────────────────

class BillPayment(models.Model):
    CATEGORY_ELECTRICITY = 'electricity'
    CATEGORY_WATER       = 'water'
    CATEGORY_INTERNET    = 'internet'
    CATEGORY_CABLE_TV    = 'cable_tv'
    CATEGORY_OTHER       = 'other'
    CATEGORY_CHOICES = [
        (CATEGORY_ELECTRICITY, 'Electricity'),
        (CATEGORY_WATER,       'Water'),
        (CATEGORY_INTERNET,    'Internet'),
        (CATEGORY_CABLE_TV,    'Cable TV'),
        (CATEGORY_OTHER,       'Other'),
    ]

    STATUS_PENDING   = 'pending'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED    = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING,   'Pending'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED,    'Failed'),
    ]

    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='bill_payments',
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    biller_name = models.CharField(max_length=255)
    biller_account = models.CharField(
        'meter / account / identifier',
        max_length=100,
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        default=generate_reference,
    )
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'bill payment'

    def __str__(self):
        return f'{self.biller_name} — ${self.amount}'


# ─────────────────────────────────────────────
#  Loan Application
# ─────────────────────────────────────────────

class LoanApplication(models.Model):
    LOAN_PERSONAL = 'personal'
    LOAN_BUSINESS = 'business'
    LOAN_MORTGAGE = 'mortgage'
    LOAN_AUTO     = 'auto'
    LOAN_STUDENT  = 'student'
    LOAN_CHOICES = [
        (LOAN_PERSONAL, 'Personal Loan'),
        (LOAN_BUSINESS, 'Business Loan'),
        (LOAN_MORTGAGE, 'Mortgage'),
        (LOAN_AUTO,     'Auto Loan'),
        (LOAN_STUDENT,  'Student Loan'),
    ]

    STATUS_DRAFT        = 'draft'
    STATUS_SUBMITTED    = 'submitted'
    STATUS_UNDER_REVIEW = 'under_review'
    STATUS_APPROVED     = 'approved'
    STATUS_REJECTED     = 'rejected'
    STATUS_DISBURSED    = 'disbursed'
    STATUS_CLOSED       = 'closed'
    STATUS_CHOICES = [
        (STATUS_DRAFT,        'Draft'),
        (STATUS_SUBMITTED,    'Submitted'),
        (STATUS_UNDER_REVIEW, 'Under Review'),
        (STATUS_APPROVED,     'Approved'),
        (STATUS_REJECTED,     'Rejected'),
        (STATUS_DISBURSED,    'Disbursed'),
        (STATUS_CLOSED,       'Closed'),
    ]

    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='loan_applications',
    )
    loan_type = models.CharField(max_length=20, choices=LOAN_CHOICES)
    amount_requested = models.DecimalField(max_digits=14, decimal_places=2)
    amount_approved = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    interest_rate = models.DecimalField(
        'annual interest rate (%)',
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    tenure_months = models.PositiveIntegerField('repayment period (months)')
    purpose = models.TextField(blank=True)
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    reference = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        default=generate_reference,
    )
    applied_at   = models.DateTimeField(null=True, blank=True)
    reviewed_at  = models.DateTimeField(null=True, blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'loan application'

    def __str__(self):
        return (
            f'{self.reference} | {self.get_loan_type_display()} ${self.amount_requested}'
        )

    def submit(self):
        self.status = self.STATUS_SUBMITTED
        self.applied_at = timezone.now()
        self.save(update_fields=['status', 'applied_at', 'updated_at'])


# ─────────────────────────────────────────────
#  Currency Swap
# ─────────────────────────────────────────────

class CurrencySwap(models.Model):
    STATUS_PENDING   = 'pending'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED    = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING,   'Pending'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED,    'Failed'),
    ]

    account       = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='currency_swaps',
    )
    from_currency = models.CharField(max_length=3)
    to_currency   = models.CharField(max_length=3)
    amount_from   = models.DecimalField(max_digits=14, decimal_places=6)
    amount_to     = models.DecimalField(max_digits=14, decimal_places=6)
    exchange_rate = models.DecimalField(max_digits=14, decimal_places=6)
    reference     = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        default=generate_reference,
    )
    status     = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'currency swap'

    def __str__(self):
        return f'{self.from_currency} → {self.to_currency} | rate {self.exchange_rate}'


# ─────────────────────────────────────────────
#  Deposit Request
# ─────────────────────────────────────────────

class DepositRequest(models.Model):
    METHOD_BANK_TRANSFER = 'bank_transfer'
    METHOD_CARD          = 'card'
    METHOD_CHOICES = [
        (METHOD_BANK_TRANSFER, 'ACH / Wire Transfer'),
        (METHOD_CARD,          'Debit / Credit Card'),
    ]

    STATUS_PENDING   = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_EXPIRED   = 'expired'
    STATUS_CHOICES = [
        (STATUS_PENDING,   'Pending'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_EXPIRED,   'Expired'),
    ]

    account      = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='deposits',
    )
    amount       = models.DecimalField(max_digits=14, decimal_places=2)
    method       = models.CharField(max_length=20, choices=METHOD_CHOICES)
    reference    = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        default=generate_reference,
    )
    status       = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    created_at   = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'deposit request'

    def __str__(self):
        return f'{self.reference} ${self.amount} via {self.method}'


# ─────────────────────────────────────────────
#  Virtual Card
# ─────────────────────────────────────────────

class VirtualCard(models.Model):
    CARD_VISA       = 'visa'
    CARD_MASTERCARD = 'mastercard'
    CARD_CHOICES = [
        (CARD_VISA,       'Visa'),
        (CARD_MASTERCARD, 'Mastercard'),
    ]

    STATUS_ACTIVE  = 'active'
    STATUS_FROZEN  = 'frozen'
    STATUS_EXPIRED = 'expired'
    STATUS_CHOICES = [
        (STATUS_ACTIVE,  'Active'),
        (STATUS_FROZEN,  'Frozen'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    account        = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='cards',
    )
    card_type      = models.CharField(
        max_length=12,
        choices=CARD_CHOICES,
        default=CARD_VISA,
    )
    last_four      = models.CharField(max_length=4)
    expiry         = models.DateField()
    cvv_hash       = models.CharField(
        max_length=128,
        help_text='Hashed CVV — never store plaintext',
    )
    spending_limit = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('2500.00'),
    )
    status     = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'virtual card'

    def __str__(self):
        return f'{self.get_card_type_display()} ••{self.last_four}'
    

    

class ChatSession(models.Model):
    """Holds a live support channel between an authenticated user and staff linked to an intercepted action."""
    
    STATUS_PENDING = 'PENDING'
    STATUS_REVIEW = 'UNDER_REVIEW'
    STATUS_APPROVED = 'APPROVED'
    STATUS_DECLINED = 'DECLINED'
    STATUS_RESOLVED = 'RESOLVED'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Review'),
        (STATUS_REVIEW, 'Under Administrative Review'),
        (STATUS_APPROVED, 'Approved & Actioned'),
        (STATUS_DECLINED, 'Declined / Rejected'),
        (STATUS_RESOLVED, 'Resolved & Closed'),
    ]

    support_id = models.CharField(
        max_length=50, 
        unique=True, 
        default=generate_support_id,
        help_text="Unique support reference ID code used for resolving operations."
    )
    account = models.ForeignKey(
        'Account',
        on_delete=models.CASCADE,
        related_name='chat_sessions'
    )
    title = models.CharField(
        max_length=255,
        blank=True,
        help_text="Custom title configured by administrators, or automatically generated from actions."
    )
    linked_action = models.CharField(
        max_length=100,
        blank=True,
        help_text="The feature context being routed (e.g., Local Transfer, Pay Bills, Virtual Card Request)"
    )
    meta_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Preserved raw submission data captured from the client form structure."
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        help_text="Current state of the request. Admin handles manual execution updates here."
    )
    is_resolved = models.BooleanField(
        default=False,
        help_text="General structural archive toggle flag."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def save(self, *args, **kwargs):
        # Automatically generate structural thread text contexts if empty
        if not self.title:
            if self.linked_action:
                self.title = f"Verification Pipeline: {self.linked_action}"
            else:
                self.title = f"Operations Desk File — {self.support_id}"
        
        # Keep status synchronizations matched with the boolean flag field if moved to final states
        if self.status in [self.STATUS_RESOLVED, self.STATUS_DECLINED]:
            self.is_resolved = True
        else:
            self.is_resolved = False

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} ({self.support_id}) — [{self.get_status_display()}]"


class ChatMessage(models.Model):
    """Individual messages inside a Support Chat Session."""
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )
    message_text = models.TextField()
    is_from_staff = models.BooleanField(
        default=False,
        help_text="True if a support agent sent this, False if the account owner sent it."
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"[{self.session.support_id}] Send State: {'Staff' if self.is_from_staff else 'Client'}"