import secrets
import string
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
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
#  OTP Escrow Mixin
# ─────────────────────────────────────────────
#
#  Shared verification scaffolding for any model whose financial effect must be
#  held back until a support agent has researched the request and shared an
#  OTP with the customer through its linked verification process (see
#  ChatSession below).
#
#  Today this is used by LocalTransfer and InternationalTransfer. Deposits,
#  card requests, loans, and bill payments will get their own review workflow
#  later — they don't inherit this mixin until that's designed, since their
#  business process differs (this is purely the "research → share code →
#  customer redeems code" pattern that transfers need).
#
#  The OTP itself is generated automatically the moment the row is created
#  (so it's already sitting there for the agent to look up) — but it can't be
#  redeemed until the agent explicitly marks it as sent, which is what
#  actually starts the customer-facing 48h window. Nothing here moves money —
#  that stays the caller's responsibility, since the exact ledger/balance
#  effect differs per model.

class OTPEscrowMixin(models.Model):
    STATUS_PENDING_REVIEW = 'pending_review'
    STATUS_OTP_ISSUED     = 'otp_issued'
    STATUS_COMPLETED      = 'completed'
    STATUS_EXPIRED        = 'expired'
    STATUS_FAILED         = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING_REVIEW, 'Pending — Awaiting Support Review'),
        (STATUS_OTP_ISSUED,     'OTP Sent — Awaiting Customer Confirmation'),
        (STATUS_COMPLETED,      'Completed'),
        (STATUS_EXPIRED,        'Expired'),
        (STATUS_FAILED,         'Failed'),
    ]

    OTP_VALID_FOR  = timedelta(hours=48)
    MAX_OTP_ATTEMPTS = 5

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING_REVIEW,
    )

    # --- Security/Support Escrow Fields ---
    required_otp = models.CharField(
        'Support OTP',
        max_length=6,
        default=generate_otp,
        editable=False,
        help_text="Generated automatically when this transfer is created. Visible "
                   "to support staff only — once research is done, the agent copies "
                   "this code and pastes it into the customer's verification chat."
    )
    otp_sent_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Stamped when the agent marks the code as shared with the customer "
                   "in chat. This — not the creation time — starts the 48h window."
    )
    otp_expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text="otp_sent_at + 48h. The code stops being redeemable after this point."
    )
    otp_attempts = models.PositiveSmallIntegerField(default=0)
    is_otp_verified = models.BooleanField(default=False)

    class Meta:
        abstract = True

    # --- Behaviour ---

    @property
    def is_otp_expired(self):
        return bool(
            self.otp_expires_at
            and not self.is_otp_verified
            and timezone.now() > self.otp_expires_at
        )

    @property
    def verification_session(self):
        """The ChatSession process driving this object's research/OTP workflow, if any."""
        content_type = ContentType.objects.get_for_model(self.__class__)
        return ChatSession.objects.filter(
            content_type=content_type, object_id=self.pk
        ).first()

    def mark_otp_sent(self):
        """
        Called by the support agent right after they paste the existing
        required_otp into the chat. Starts the 48h redemption window —
        does NOT generate a new code, the code already existed.
        """
        self.otp_sent_at = timezone.now()
        self.otp_expires_at = self.otp_sent_at + self.OTP_VALID_FOR
        self.status = self.STATUS_OTP_ISSUED
        self.save(update_fields=['otp_sent_at', 'otp_expires_at', 'status'])
        return self.required_otp

    def verify_otp(self, submitted_code):
        """
        Called when the customer redeems the code to finalize the transaction.
        Returns (ok: bool, message: str). Does NOT move money — caller does that
        only when ok is True, inside its own atomic block.
        """
        if self.is_otp_verified:
            return False, 'This transaction has already been completed.'

        if self.status != self.STATUS_OTP_ISSUED:
            return False, 'Support has not shared a verification code for this transaction yet.'

        if self.is_otp_expired:
            self.status = self.STATUS_EXPIRED
            self.save(update_fields=['status'])
            return False, 'This code has expired. Please contact support to restart verification.'

        self.otp_attempts += 1

        if submitted_code.strip() != self.required_otp:
            if self.otp_attempts >= self.MAX_OTP_ATTEMPTS:
                self.status = self.STATUS_FAILED
                self.save(update_fields=['otp_attempts', 'status'])
                return False, 'Too many incorrect attempts. Please contact support to restart verification.'
            self.save(update_fields=['otp_attempts'])
            return False, 'Incorrect code.'

        self.is_otp_verified = True
        self.status = self.STATUS_COMPLETED
        self.save(update_fields=['is_otp_verified', 'status', 'otp_attempts'])
        return True, 'Verified.'


# ─────────────────────────────────────────────
#  Local Transfer (US Domestic ACH / Wire)
# ─────────────────────────────────────────────


class LocalTransfer(OTPEscrowMixin):
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
    # NOTE: this amount is only a reservation. It is NOT debited from the
    # sender's balance until verify_otp() succeeds — see views.py.
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    description = models.CharField(max_length=255, blank=True)
    reference = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        default=generate_reference,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(OTPEscrowMixin.Meta):
        ordering = ['-created_at']
        verbose_name = 'local transfer'

    def __str__(self):
        return f'{self.reference} → {self.recipient_name} (${self.amount})'
    


# ─────────────────────────────────────────────
#  International Transfer
# ─────────────────────────────────────────────

class InternationalTransfer(OTPEscrowMixin):
    PAYMENT_METHOD_CHOICES = [
        ('wire',    'Wire Transfer'),
        ('crypto',  'Cryptocurrency'),
        ('paypal',  'PayPal'),
        ('wise',    'Wise Transfer'),
        ('cashapp', 'Cash App'),
        ('skrill',  'Skrill'),
        ('venmo',   'Venmo'),
        ('zelle',   'Zelle'),
        ('revolut', 'Revolut'),
        ('alipay',  'Alipay'),
        ('wechat',  'WeChat Pay'),
    ]

    sender = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='international_transfers',
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default='wire',
    )
    recipient_name = models.CharField(max_length=255)
    # Primary identifier — IBAN, wallet address, email, Cashtag, etc.
    recipient_account = models.CharField(max_length=255)
    # Secondary identifier — SWIFT/BIC, network type, region, phone, etc.
    routing_code = models.CharField(max_length=255, blank=True)
    settlement_currency = models.CharField(max_length=10, default='USD')
    description = models.CharField(max_length=255, blank=True)
    amount_sent = models.DecimalField(
        'amount (source currency)',
        max_digits=14,
        decimal_places=2,
    )
    source_currency = models.CharField(max_length=3, default='USD')
    reference = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        default=generate_reference,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(OTPEscrowMixin.Meta):
        ordering = ['-created_at']
        verbose_name = 'international transfer'

    def __str__(self):
        return f'{self.reference} → {self.recipient_name} ({self.settlement_currency})'


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
            f'{self.reference} | {self.get_loan_type_display()} ${self.amount_requested}' #type: ignore
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
        return f'{self.get_card_type_display()} ••{self.last_four}' #type: ignore
    

    

class ChatSession(models.Model):
    """
    A verification PROCESS for a single transaction — not a general help-desk thread.
    One of these is opened automatically the moment a transfer is created, and it
    stays open until the agent issues an OTP and the customer redeems it (or it's
    declined/expires). It links back to the exact object it's verifying via a
    generic relation, so future flows (deposits, cards, loans, bills) can plug in
    the same way without new FK columns on this model each time.
    """

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
        help_text="Human-readable label for the process (e.g., 'Local Transfer', 'International Transfer')."
    )

    # --- Generic link to the transaction object this process is verifying ---
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True, blank=True,
        help_text="Model of the underlying transaction (e.g. LocalTransfer, InternationalTransfer).",
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    linked_object = GenericForeignKey('content_type', 'object_id')

    meta_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Non-sensitive contextual notes captured for the agent. Never store credentials here."
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
        constraints = [
            models.UniqueConstraint(
                fields=['content_type', 'object_id'],
                condition=models.Q(content_type__isnull=False),
                name='one_verification_session_per_object',
            ),
        ]

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
        return f"{self.title} ({self.support_id}) — [{self.get_status_display()}]" #type: ignore


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