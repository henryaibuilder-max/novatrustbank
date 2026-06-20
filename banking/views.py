from decimal import Decimal, InvalidOperation
import json

from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .models import (
    Account,
    LocalTransfer,
    InternationalTransfer,  # Added
    LoanApplication,
    Transaction,
    ChatMessage,
    ChatSession
)


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _get_account(user):
    account, _ = Account.objects.get_or_create(user=user)
    return account


def _daily_used(account):
    """Total debit amount dispatched today (completed + pending)."""
    today = timezone.now().date()
    return (
        Transaction.objects
        .filter(
            account=account,
            type=Transaction.TYPE_DEBIT,
            created_at__date=today,
            status__in=[Transaction.STATUS_COMPLETED, Transaction.STATUS_PENDING],
        )
        .aggregate(total=Sum('amount'))['total']
        or Decimal('0.00')
    )


def _open_verification_session(account, transfer_obj, label):
    """
    Shared helper to initialize a verification chat thread linked generic polymorphic 
    to a tracking asset transfer. Employs a strict allowlist to avoid leaking passwords.
    """
    content_type = ContentType.objects.get_for_model(transfer_obj)
    
    # Strict key allowlist mapping to avoid capturing password / raw session variables
    safe_payload = {}
    exposed_fields = [
        'recipient_name', 'recipient_bank', 'recipient_account_number', 
        'recipient_account', 'recipient_country', 'swift_code', 'swift_bic',
        'iban', 'amount', 'amount_sent', 'source_currency', 'target_currency',
        'exchange_rate', 'description', 'reference'
    ]
    
    for field in exposed_fields:
        if hasattr(transfer_obj, field):
            val = getattr(transfer_obj, field)
            safe_payload[field] = str(val) if isinstance(val, Decimal) else val

    session_instance = ChatSession.objects.create(
        account=account,
        content_type=content_type,
        object_id=transfer_obj.id,
        linked_action=label,
        meta_payload=safe_payload,
        status=ChatSession.STATUS_PENDING
    )

    # Initialize systematic audit trail logging without sensitive info leakage
    ChatMessage.objects.create(
        session=session_instance,
        message_text=(
            f"[SYSTEM AUDIT LOG]: Transfer verification initiated for '{label}'. "
            f"Reference: {transfer_obj.reference}. Awaiting administrative compliance screening."
        ),
        is_from_staff=True
    )
    return session_instance


# ─────────────────────────────────────────────
#  Dashboard & Lists
# ─────────────────────────────────────────────

@login_required
def dashboard(request):
    account = _get_account(request.user)
    transactions = (
        Transaction.objects
        .filter(account=account)
        .select_related()
        .order_by('-created_at')[:10]
    )

    now = timezone.now()
    month_qs = Transaction.objects.filter(
        account=account,
        created_at__year=now.year,
        created_at__month=now.month,
    )
    monthly_deposits = (
        month_qs
        .filter(type=Transaction.TYPE_CREDIT, status=Transaction.STATUS_COMPLETED)
        .aggregate(total=Sum('amount'))['total'] or 0
    )
    monthly_expenses = (
        month_qs
        .filter(type=Transaction.TYPE_DEBIT, status=Transaction.STATUS_COMPLETED)
        .aggregate(total=Sum('amount'))['total'] or 0
    )
    pending_total = (
        Transaction.objects
        .filter(account=account, status=Transaction.STATUS_PENDING)
        .aggregate(total=Sum('amount'))['total'] or 0
    )
    total_volume = (
        Transaction.objects
        .filter(account=account, status=Transaction.STATUS_COMPLETED)
        .aggregate(total=Sum('amount'))['total'] or 0
    )
    return render(request, 'dashboard/index.html', {
        'account': account,
        'transactions': transactions,
        'stats': {
            'actual_balance':   f'{account.balance:,.2f}',
            'balance':          f'{account.balance:,.2f}',
            'monthly_deposits': f'{monthly_deposits:,.2f}',
            'monthly_expenses': f'{monthly_expenses:,.2f}',
            'pending_total':    f'{pending_total:,.2f}',
            'total_volume':     f'{total_volume:,.2f}',
        },
    })


@login_required
def transactions(request):
    account = _get_account(request.user)
    qs = Transaction.objects.filter(account=account).order_by('-created_at')

    tx_type   = request.GET.get('type', '').strip()
    category  = request.GET.get('category', '').strip()
    status    = request.GET.get('status', '').strip()
    date_from = request.GET.get('from', '').strip()
    date_to   = request.GET.get('to', '').strip()

    if tx_type in (Transaction.TYPE_CREDIT, Transaction.TYPE_DEBIT):
        qs = qs.filter(type=tx_type)

    valid_categories = {c for c, _ in Transaction.CATEGORY_CHOICES}
    if category in valid_categories:
        qs = qs.filter(category=category)

    valid_statuses = {s for s, _ in Transaction.STATUS_CHOICES}
    if status in valid_statuses:
        qs = qs.filter(status=status)

    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    # Build reference → ChatSession map
    references = list(qs.values_list('reference', flat=True))
    sessions = ChatSession.objects.filter(account=account)

    tx_sessions = {}
    for s in sessions:
        payload = s.meta_payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                continue
        ref = payload.get('reference') if isinstance(payload, dict) else None
        if ref and ref in references:
            tx_sessions[ref] = s

    return render(request, 'dashboard/transactions.html', {
        'account':      account,
        'transactions': qs,
        'tx_sessions':  tx_sessions,
        'filters': {
            'type':     tx_type,
            'category': category,
            'status':   status,
            'from':     date_from,
            'to':       date_to,
        },
        'type_choices':     Transaction.TYPE_CHOICES,
        'category_choices': Transaction.CATEGORY_CHOICES,
        'status_choices':   Transaction.STATUS_CHOICES,
    })


@login_required
def cards(request):
    account = _get_account(request.user)
    return render(request, 'dashboard/cards.html', {
        'account': account,
        'cards':   account.cards.all(),
    })


# ─────────────────────────────────────────────
#  Local Transfer
# ─────────────────────────────────────────────

@login_required
def local_transfer(request):
    account = _get_account(request.user)

    if request.method == 'POST':
        holder_name    = request.POST.get('account_holder_name', '').strip()
        account_number = request.POST.get('account_number', '').strip()
        bank_name      = request.POST.get('bank_name', '').strip()
        description    = request.POST.get('description', '').strip()
        raw_amount     = request.POST.get('amount', '').strip()
        password       = request.POST.get('password', '')

        errors = []

        if not holder_name:
            errors.append('Account holder name is required.')
        if not account_number or not account_number.isdigit() or len(account_number) != 10:
            errors.append('A valid 10-digit account number is required.')
        if not bank_name:
            errors.append('Bank name is required.')
        if not password:
            errors.append('Your account password is required to authorise this transfer.')

        try:
            amount = Decimal(raw_amount)
            if amount < Decimal('10.00'):
                errors.append('Minimum transfer amount is $10.00.')
        except (InvalidOperation, ValueError):
            amount = None
            errors.append('Enter a valid transfer amount.')

        if not errors:
            user = authenticate(email=request.user.email, password=password)
            if user is None:
                errors.append('Incorrect password. Transfer not authorised.')

        if not errors:
            if amount > account.balance:
                errors.append(f'Insufficient balance. Available: ${account.balance:,.2f}.')

            daily_used = _daily_used(account)
            daily_remaining = account.daily_limit - daily_used
            if amount > daily_remaining:
                errors.append(f'Daily transfer limit exceeded. Remaining today: ${daily_remaining:,.2f}.')

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'dashboard/transfer_local.html', {
                'account': account,
                'form_data': request.POST,
            })

        try:
            with db_transaction.atomic():
                # Balance deduction removed; funds are reserved by the record state
                transfer = LocalTransfer.objects.create(
                    sender=account,
                    recipient_account_number=account_number,
                    recipient_name=holder_name,
                    recipient_bank=bank_name,
                    amount=amount,
                    description=description,
                    status=LocalTransfer.STATUS_PENDING_REVIEW,
                )

                # Reference pinned explicitly to match the transfer item mapping
                Transaction.objects.create(
                    account=account,
                    type=Transaction.TYPE_DEBIT,
                    category=Transaction.CATEGORY_TRANSFER,
                    amount=amount,
                    currency=account.currency,
                    balance_after=account.balance,
                    description=description or f'Transfer to {holder_name}',
                    counterpart_name=holder_name,
                    counterpart_account=account_number,
                    status=Transaction.STATUS_PENDING,
                    reference=transfer.reference,
                )

            session = _open_verification_session(account, transfer, "Local Transfer")
            messages.success(request, f'Transfer tracking reference {transfer.reference} initiated. Verification mandatory.')
            return redirect('banking:support_chat_detail', support_id=session.support_id)

        except Exception:
            messages.error(request, 'A system error occurred while processing the transfer.')

    return render(request, 'dashboard/transfer_local.html', {'account': account})


# ─────────────────────────────────────────────
#  International Transfer
# ─────────────────────────────────────────────

@login_required
def international_transfer(request):
    account = _get_account(request.user)

    if request.method == 'POST':
        payment_method   = request.POST.get('payment_method_type', 'wire').strip()
        recipient_name   = request.POST.get('recipient_name', '').strip()
        recipient_acct   = request.POST.get('account_identifier_primary', '').strip()
        routing_code     = request.POST.get('account_identifier_secondary', '').strip()
        settlement_ccy   = request.POST.get('settlement_currency', 'USD').strip()
        description      = request.POST.get('description', '').strip()
        raw_amount       = request.POST.get('amount', '').strip()
        password         = request.POST.get('password', '')

        errors = []

        if not recipient_name:
            errors.append('Recipient name is required.')
        if not recipient_acct:
            errors.append('Account / wallet / handle identifier is required.')
        if not routing_code:
            errors.append('Routing code / secondary identifier is required.')
        if not password:
            errors.append('Account password is required.')

        try:
            amount_sent = Decimal(raw_amount)
            if amount_sent < Decimal('10.00'):
                errors.append('Minimum transfer amount is $10.00.')
        except (InvalidOperation, ValueError):
            amount_sent = None
            errors.append('Enter a valid transfer amount.')

        if not errors:
            user = authenticate(email=request.user.email, password=password)
            if user is None:
                errors.append('Incorrect account password.')

        if not errors:
            if amount_sent > account.balance:
                errors.append(f'Insufficient balance. Available: ${account.balance:,.2f}.')

            daily_used = _daily_used(account)
            if amount_sent > (account.daily_limit - daily_used):
                errors.append('Daily transfer limit reached.')

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'dashboard/transfer_international.html', {
                'account': account,
                'form_data': request.POST,
            })

        try:
            with db_transaction.atomic():
                transfer = InternationalTransfer.objects.create(
                    sender=account,
                    payment_method=payment_method,
                    recipient_name=recipient_name,
                    recipient_account=recipient_acct,
                    routing_code=routing_code,
                    settlement_currency=settlement_ccy,
                    amount_sent=amount_sent,
                    source_currency=account.currency,
                    description=description,
                    status=InternationalTransfer.STATUS_PENDING_REVIEW,
                )

                Transaction.objects.create(
                    account=account,
                    type=Transaction.TYPE_DEBIT,
                    category=Transaction.CATEGORY_TRANSFER,
                    amount=amount_sent,
                    currency=account.currency,
                    balance_after=account.balance,
                    description=description or f'International transfer to {recipient_name}',
                    counterpart_name=recipient_name,
                    counterpart_account=recipient_acct,
                    status=Transaction.STATUS_PENDING,
                    reference=transfer.reference,
                )

            session = _open_verification_session(account, transfer, "International Transfer")
            messages.success(request, f'Transfer submitted. Reference: {transfer.reference}.')
            return redirect('banking:support_chat_detail', support_id=session.support_id)

        except Exception:
            messages.error(request, 'A processing error occurred. Please try again.')

    return render(request, 'dashboard/transfer_international.html', {'account': account})
# ─────────────────────────────────────────────
#  OTP Redemption View (Money Movement)
# ─────────────────────────────────────────────

@login_required
@csrf_protect
def verify_otp(request, reference):
    """
    Decoupled redemption terminal to clear verification holding locks inside a safe 48h window.
    """
    account = _get_account(request.user)
    
    # Context lookup spanning polymorphic targets safely verified against identity ownership
    transfer = None
    is_international = False
    
    local_lookup = LocalTransfer.objects.filter(reference=reference, sender=account).first()
    if local_lookup:
        transfer = local_lookup
    else:
        int_lookup = InternationalTransfer.objects.filter(reference=reference, sender=account).first()
        if int_lookup:
            transfer = int_lookup
            is_international = True

    if not transfer:
        messages.error(request, 'Secured transfer reference context index not found.')
        return redirect('banking:dashboard')

    if request.method == 'POST':
        submitted_code = request.POST.get('otp_code', '').strip()
        
        # Invoke inner business rules tracking window limits and validation flags
        is_valid, error_msg = transfer.verify_otp(submitted_code)
        
        if is_valid:
            try:
                debit_amount = transfer.amount_sent if is_international else transfer.amount
                with db_transaction.atomic():
                
                    account.refresh_from_db()
                    if account.balance < debit_amount:
                        messages.error(request, "Execution halted: Balance insufficient at clearing execution point.")
                        return redirect('banking:dashboard')
                    
                    # Deduct the ledger balance structural reserves
                    account.balance -= debit_amount
                    account.save(update_fields=['balance', 'updated_at'])
                    
                    # Synchronize financial transactions tracking index ledger rows
                    ledger_row = Transaction.objects.get(reference=reference, account=account)
                    ledger_row.status = Transaction.STATUS_COMPLETED
                    ledger_row.balance_after = account.balance
                    ledger_row.save(update_fields=['status', 'balance_after', 'updated_at'])
                    
                    # Cleanly resolve structural support tickers
                    content_type = ContentType.objects.get_for_model(transfer)
                    chat_session = ChatSession.objects.filter(
                        content_type=content_type, 
                        object_id=transfer.id
                    ).first()
                    
                    if chat_session:
                        chat_session.status = ChatSession.STATUS_RESOLVED
                        chat_session.save(update_fields=['status', 'updated_at'])
                        
                        ChatMessage.objects.create(
                            session=chat_session,
                            message_text="[SYSTEM NOTICE]: Out-of-band identity token authenticated successfully. Funds released.",
                            is_from_staff=True
                        )

                messages.success(request, f"Transaction successfully executed. Ledger batch {reference} cleared.")
                return redirect('banking:transactions')
                
            except Exception:
                messages.error(request, "Internal structural fault registering database settlement updates.")
        else:
            messages.error(request, error_msg or "Token verification error.")

    return render(request, 'dashboard/verify_otp.html', {
        'account': account,
        'transfer': transfer,
        'reference': reference
    })


# ─────────────────────────────────────────────
#  Support Tickets & Chat Flow
# ─────────────────────────────────────────────

@login_required
def submit_action_to_support(request):
    """
    Administrative catch-all workspace for generic actions (Cards, Deposits, Bills).
    Strictly allowlisted parameter mapping to ensure sensitive credentials never log.
    """
    if request.method == 'POST':
        account = _get_account(request.user)
        linked_action = request.POST.get('action_name', 'Manual Settlement Routine')
        
        # Enforce strict key allowlists instead of raw dictionary collection dumps
        clean_payload = {}
        allowed_keys = ['bill_type', 'biller_id', 'card_id', 'deposit_method', 'amount', 'notes']
        
        for key in allowed_keys:
            if key in request.POST:
                clean_payload[key] = request.POST.get(key).strip()
        
        session_instance = ChatSession.objects.create(
            account=account,
            linked_action=linked_action,
            meta_payload=clean_payload,
            status=ChatSession.STATUS_PENDING
        )
        
        ChatMessage.objects.create(
            session=session_instance,
            message_text=f"Support workflow assigned safely under '{linked_action}'.",
            is_from_staff=True
        )

        messages.info(request, f"Processing submission categorized under tracking context: {session_instance.support_id}")
        return redirect('banking:support_chat_detail', support_id=session_instance.support_id)

    return redirect('banking:dashboard')


@login_required
def support_chat_list(request):
    account = _get_account(request.user)
    sessions = ChatSession.objects.filter(account=account).order_by('-created_at')
    return render(request, 'dashboard/support_list.html', {
        'account': account,
        'sessions': sessions
    })


@login_required
def support_chat_detail(request, support_id):
    account = _get_account(request.user)
    session_obj = get_object_or_404(ChatSession, support_id=support_id, account=account)
    
    return render(request, 'dashboard/support_detail.html', {
        'account': account,
        'session': session_obj,
        'linked_object': session_obj.linked_object,  # Exposed for targeted UI conditional loops
        'messages_list': session_obj.messages.all().order_by('id')
    })


@login_required
@require_http_methods(["GET"])
def poll_chat_messages(request, support_id):
    try:
        session = ChatSession.objects.get(support_id=support_id)    
    except ChatSession.DoesNotExist:
        return JsonResponse({'error': 'Active session validation failure'}, status=404)

    try:
        last_id = int(request.GET.get('last_id', 0))
    except ValueError:
        last_id = 0

    new_messages = session.messages.filter(id__gt=last_id).order_by('id')

    message_payload = []
    for msg in new_messages:
        message_payload.append({
            'id': msg.id,
            'message_text': msg.message_text,
            'is_from_staff': msg.is_from_staff,
            'timestamp': msg.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        })

    return JsonResponse({'messages': message_payload})


@login_required
@csrf_protect
@require_http_methods(["POST"])
def send_chat_message(request, support_id):
    try:
        session = ChatSession.objects.get(support_id=support_id)
    except ChatSession.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Session expired'}, status=404)

    try:
        payload = json.loads(request.body)
        message_text = payload.get('message', '').strip()
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Malformed request data format'}, status=400)

    if not message_text:
        return JsonResponse({'status': 'error', 'message': 'Empty inputs rejected'}, status=400)

    ChatMessage.objects.create(
        session=session,
        sender=request.user,
        message_text=message_text,
        is_from_staff=request.user.is_staff
    )

    return JsonResponse({'status': 'success'})


# ─────────────────────────────────────────────
#  Stubs & Simple Interfaces
# ─────────────────────────────────────────────

@login_required
def deposit(request):
    account = _get_account(request.user)
    return render(request, 'dashboard/deposit.html', {'account': account})


@login_required
def currency_swap(request):
    account = _get_account(request.user)
    return render(request, 'dashboard/currency_swap.html', {'account': account})


@login_required
def pay_bills(request):
    account = _get_account(request.user)
    return render(request, 'dashboard/pay_bills.html', {'account': account})


LOAN_RATES = {
    'personal': Decimal('14.5'),
    'business': Decimal('12.0'),
    'salary':   Decimal('18.0'),
}

@login_required
def loans(request):
    account = _get_account(request.user)

    if request.method == 'POST':
        loan_type_key  = request.POST.get('loan_type', 'personal').strip()
        raw_amount     = request.POST.get('amount', '').strip()
        raw_months     = request.POST.get('tenure_months', '').strip()
        purpose        = request.POST.get('purpose', '').strip()

        errors = []

        try:
            amount = Decimal(raw_amount)
            if amount < Decimal('50000.00'):
                errors.append('Minimum loan request is ₦50,000.00.')
            if amount > Decimal('5000000.00'):
                errors.append('Maximum loan request is ₦5,000,000.00.')
        except (InvalidOperation, ValueError):
            amount = None
            errors.append('Enter a valid loan amount.')

        try:
            months = int(raw_months)
            if months not in (3, 6, 12, 24):
                errors.append('Select a valid repayment period.')
        except (ValueError, TypeError):
            months = None
            errors.append('Select a valid repayment period.')

        loan_type_map = {
            'personal': LoanApplication.LOAN_PERSONAL,
            'business': LoanApplication.LOAN_BUSINESS,
            'salary':   LoanApplication.LOAN_PERSONAL,
        }
        if loan_type_key not in loan_type_map:
            errors.append('Invalid loan type selected.')

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            loan = LoanApplication.objects.create(
                account=account,
                loan_type=loan_type_map[loan_type_key],
                amount_requested=amount,
                interest_rate=LOAN_RATES.get(loan_type_key, Decimal('14.5')),
                tenure_months=months,
                purpose=purpose,
                status=LoanApplication.STATUS_SUBMITTED,
                applied_at=timezone.now(),
            )
            messages.success(request, f'Loan application submitted successfully. Reference: {loan.reference}.')
            return redirect('banking:loans')

    loan_applications = account.loan_applications.all()
    loans_with_progress = []
    for loan in loan_applications:
        approved = loan.amount_approved or loan.amount_requested
        if loan.status in (LoanApplication.STATUS_DISBURSED, LoanApplication.STATUS_CLOSED):
            paid = approved - (loan.amount_approved or approved)
            pct  = min(int((paid / approved) * 100), 100) if approved else 0
        else:
            pct = 0
            
        loan.repayment_percentage = pct
        loans_with_progress.append(loan)

    return render(request, 'dashboard/loans.html', {
        'account': account,
        'loans':   loans_with_progress,
    })