from django.contrib import admin

from .models import (
    Account,
    BillPayment,
    CurrencySwap,
    DepositRequest,
    InternationalTransfer,
    LoanApplication,
    LocalTransfer,
    Transaction,
    VirtualCard,
    ChatSession,
    ChatMessage
)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display  = ('user', 'currency', 'balance', 'btc_balance', 'daily_limit', 'is_verified')
    list_filter   = ('currency', 'is_verified')
    search_fields = ('user__email', 'user__first_name', 'user__last_name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display  = ('reference', 'account', 'type', 'category', 'amount', 'currency', 'status', 'created_at')
    list_filter   = ('type', 'category', 'status', 'currency')
    search_fields = ('reference', 'description', 'counterpart_name', 'counterpart_account')
    readonly_fields = ('reference', 'created_at', 'updated_at')
    date_hierarchy  = 'created_at'


@admin.register(LocalTransfer)
class LocalTransferAdmin(admin.ModelAdmin):
    list_display  = ('reference', 'sender', 'recipient_name', 'amount', 'status', 'created_at')
    list_filter   = ('status',)
    search_fields = ('reference', 'recipient_name', 'recipient_account_number')
    readonly_fields = ('reference', 'created_at')


@admin.register(InternationalTransfer)
class InternationalTransferAdmin(admin.ModelAdmin):
    list_display  = ('reference', 'sender', 'recipient_name', 'amount_sent', 'source_currency', 'target_currency', 'status')
    list_filter   = ('status', 'source_currency', 'target_currency')
    search_fields = ('reference', 'recipient_name', 'recipient_account', 'swift_bic', 'iban')
    readonly_fields = ('reference', 'created_at')


@admin.register(BillPayment)
class BillPaymentAdmin(admin.ModelAdmin):
    list_display  = ('reference', 'account', 'category', 'biller_name', 'amount', 'status', 'created_at')
    list_filter   = ('category', 'status')
    search_fields = ('reference', 'biller_name', 'biller_account')
    readonly_fields = ('reference', 'created_at')


@admin.register(LoanApplication)
class LoanApplicationAdmin(admin.ModelAdmin):
    list_display  = ('reference', 'account', 'loan_type', 'amount_requested', 'status', 'applied_at')
    list_filter   = ('loan_type', 'status')
    search_fields = ('reference', 'account__user__email')
    readonly_fields = ('reference', 'created_at', 'updated_at')


@admin.register(CurrencySwap)
class CurrencySwapAdmin(admin.ModelAdmin):
    list_display  = ('reference', 'account', 'from_currency', 'to_currency', 'amount_from', 'amount_to', 'status')
    list_filter   = ('status', 'from_currency', 'to_currency')
    readonly_fields = ('reference', 'created_at')


@admin.register(DepositRequest)
class DepositRequestAdmin(admin.ModelAdmin):
    list_display  = ('reference', 'account', 'amount', 'method', 'status', 'created_at')
    list_filter   = ('method', 'status')
    search_fields = ('reference',)
    readonly_fields = ('reference', 'created_at', 'confirmed_at')


@admin.register(VirtualCard)
class VirtualCardAdmin(admin.ModelAdmin):
    list_display  = ('account', 'card_type', 'last_four', 'expiry', 'spending_limit', 'status')
    list_filter   = ('card_type', 'status')
    search_fields = ('account__user__email', 'last_four')
    readonly_fields = ('created_at',)


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 1
    readonly_fields = ('timestamp',)
    fields = ('sender', 'message_text', 'is_from_staff', 'timestamp')

@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    # Visible monitoring rows inside system index dashboards
    list_display = ('support_id', 'account', 'title', 'linked_action', 'status', 'is_resolved', 'created_at')
    list_filter = ('status', 'is_resolved', 'linked_action', 'created_at')
    search_fields = ('support_id', 'title', 'account__user__username', 'account__user__email')
    
    # Safeguard underlying customer payloads against unintentional overwrites
    readonly_fields = ('support_id', 'created_at', 'updated_at', 'meta_payload')
    
    inlines = [ChatMessageInline]
    
    fieldsets = (
        ('Operational State Control', {
            'fields': ('status', 'is_resolved', 'support_id')
        }),
        ('Context Configurations', {
            'fields': ('title', 'account', 'linked_action')
        }),
        ('Recorded Data Vector Payload (JSON)', {
            'classes': ('collapse',),
            'fields': ('meta_payload',),
            'description': 'Raw transactional values input parameters captured upon verification form execution request pipeline.'
        }),
        ('Timestamps Log Metric', {
            'fields': ('created_at', 'updated_at')
        }),
    )