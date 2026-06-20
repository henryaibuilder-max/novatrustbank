from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.shortcuts import get_object_or_404 as get_object_or_400
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
import json
from .models import (
    Account,
    LocalTransfer,
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


# ─────────────────────────────────────────────
#  Dashboard
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
            'actual_balance':   f'{account.balance:,.2f}',  # Added to ensure template lookups don't fall back to 0.00
            'balance':          f'{account.balance:,.2f}',  # Universal fallback alias
            'monthly_deposits': f'{monthly_deposits:,.2f}',
            'monthly_expenses': f'{monthly_expenses:,.2f}',
            'pending_total':    f'{pending_total:,.2f}',
            'total_volume':     f'{total_volume:,.2f}',
        },
    })


# ─────────────────────────────────────────────
#  Transactions
# ─────────────────────────────────────────────

@login_required
def transactions(request):
    account = _get_account(request.user)

    qs = Transaction.objects.filter(account=account).order_by('-created_at')

    # Optional filters via GET params
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

    return render(request, 'dashboard/transactions.html', {
        'account':      account,
        'transactions': qs,
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


# ─────────────────────────────────────────────
#  Cards
# ─────────────────────────────────────────────

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
        account_type   = request.POST.get('account_type', '').strip()
        routing_number = request.POST.get('routing_number', '').strip()
        swift_code     = request.POST.get('swift_code', '').strip()
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
            if amount < Decimal('10.00'):  # Lowered from 100.00 to match your template's minimum $10 threshold layout rules
                errors.append('Minimum transfer amount is $10.00.')
        except (InvalidOperation, ValueError):
            amount = None
            errors.append('Enter a valid transfer amount.')

        if not errors:
            user = authenticate(
                request,
                username=request.user.username,
                password=password,
            )
            if user is None:
                errors.append('Incorrect password. Transfer not authorised.')

        if not errors:
            if amount > account.balance:
                errors.append(
                    f'Insufficient balance. Available: ${account.balance:,.2f}.'
                )

            daily_used      = _daily_used(account)
            daily_remaining = account.daily_limit - daily_used
            if amount > daily_remaining:
                errors.append(
                    f'Daily transfer limit exceeded. '
                    f'Remaining today: ${daily_remaining:,.2f}.'
                )

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'dashboard/transfer_local.html', {
                'account': account,
                'form_data': request.POST,
            })

        try:
            with db_transaction.atomic():
                account.balance -= amount
                account.save(update_fields=['balance', 'updated_at'])

                transfer = LocalTransfer.objects.create(
                    sender=account,
                    recipient_account_number=account_number,
                    recipient_name=holder_name,
                    recipient_bank=bank_name,
                    amount=amount,
                    description=description,
                    status=LocalTransfer.STATUS_PENDING,
                )

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
                )

            messages.success(
                request,
                f'Transfer of ${amount:,.2f} to {holder_name} ({bank_name}) '
                f'has been queued. Reference: {transfer.reference}.',
            )
            return redirect('banking:transactions')

        except Exception:
            messages.error(
                request,
                'A system error occurred while processing the transfer. '
                'Please try again or contact support.',
            )

    return render(request, 'dashboard/transfer_local.html', {
        'account': account,
    })


# ─────────────────────────────────────────────
#  International Transfer
# ─────────────────────────────────────────────

@login_required
def international_transfer(request):
    account = _get_account(request.user)
    return render(request, 'dashboard/transfer_international.html', {'account': account})


# ─────────────────────────────────────────────
#  Deposit
# ─────────────────────────────────────────────

@login_required
def deposit(request):
    account = _get_account(request.user)
    return render(request, 'dashboard/deposit.html', {'account': account})


# ─────────────────────────────────────────────
#  Currency Swap
# ─────────────────────────────────────────────

@login_required
def currency_swap(request):
    account = _get_account(request.user)
    return render(request, 'dashboard/currency_swap.html', {'account': account})


# ─────────────────────────────────────────────
#  Loans
# ─────────────────────────────────────────────

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
            messages.success(
                request,
                f'Loan application submitted successfully. Reference: {loan.reference}.',
            )
            return redirect('banking:loans')

    loan_applications = account.loan_applications.all()

    # Flatten the dynamic values into standard object attributes to make them direct-loop accessible
    loans_with_progress = []
    for loan in loan_applications:
        approved = loan.amount_approved or loan.amount_requested
        if loan.status in (LoanApplication.STATUS_DISBURSED, LoanApplication.STATUS_CLOSED):
            paid = approved - (loan.amount_approved or approved)
            pct  = min(int((paid / approved) * 100), 100) if approved else 0
        else:
            pct = 0
            
        # Attach the calculation right into the model object properties dynamically
        loan.repayment_percentage = pct
        loans_with_progress.append(loan)

    return render(request, 'dashboard/loans.html', {
        'account': account,
        'loans':   loans_with_progress,  # Corrected to supply the objects populated with dynamic progress stats
    })


# ─────────────────────────────────────────────
#  Pay Bills
# ─────────────────────────────────────────────

@login_required
def pay_bills(request):
    account = _get_account(request.user)
    return render(request, 'dashboard/pay_bills.html', {'account': account})


@login_required
def submit_action_to_support(request):
    """
    Unified entry endpoint for financial or administrative forms.
    Captures submitted fields raw, constructs a support ticket workspace in a PENDING status,
    and forwards the user directly to the live communication context.
    """
    if request.method == 'POST':
        account = _get_account(request.user)
        linked_action = request.POST.get('action_name', 'Manual Ledger Settlement')
        
        # Filter request parameters, discarding internal verification tokens cleanly
        payload = {k: v for k, v in request.POST.items() if k not in ['csrf_token', 'csrfmiddlewaretoken', 'action_name']}
        
        # Persist structured parameter vectors into database engine storage maps
        session_instance = ChatSession.objects.create(
            account=account,
            linked_action=linked_action,
            meta_payload=payload,
            status=ChatSession.STATUS_PENDING
        )
        
        # Append systemic audit metadata entry tracking parameters immediately
        ChatMessage.objects.create(
            session=session_instance,
            message_text=(
                f"[SYSTEM AUDIT LOG]: Request captured for workflow task '{linked_action}'. "
                f"Status initialized to PENDING. Parameters recorded for review: {json.dumps(payload)}"
            ),
            is_from_staff=True
        )

        messages.info(
            request, 
            f"Your processing request has been submitted to support safely. Reference ID: {session_instance.support_id}"
        )
        return redirect('banking:support_chat_detail', support_id=session_instance.support_id)

    return redirect('banking:dashboard')    



@login_required
def support_chat_list(request):
    """Displays user ticket interaction historical summaries."""
    account = _get_account(request.user)
    sessions = ChatSession.objects.filter(account=account)
    return render(request, 'dashboard/support_list.html', {
        'account': account,
        'sessions': sessions
    })


@login_required
def support_chat_detail(request, support_id):
    """Focus screen layout monitoring an ongoing live ticket workflow thread."""
    account = _get_account(request.user)
    session_obj = get_object_or_400(ChatSession, support_id=support_id, account=account)
    
    return render(request, 'dashboard/support_detail.html', {
        'account': account,
        'session': session_obj,
        'messages_list': session_obj.messages.all()
    })


@login_required
@require_http_methods(["GET"])
def poll_chat_messages(request, support_id):
    """Fetches chat records updated since the last user sync interval index."""
    try:
        session = ChatSession.objects.get(support_id=support_id)
    except ChatSession.DoesNotExist:
        return JsonResponse({'error': 'Active session validation failure'}, status=404)

    # Grab the client's last seen tracking ID from query parameters
    try:
        last_id = int(request.GET.get('last_id', 0))
    except ValueError:
        last_id = 0

    # Query only for messages created after the last synchronized message ID
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
    """Handles submission of incoming support messages over HTTP POST."""
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

    # Persist the message directly into the database
    ChatMessage.objects.create(
        session=session,
        sender=request.user,
        message_text=message_text,
        is_from_staff=request.user.is_staff
    )

    return JsonResponse({'status': 'success'})