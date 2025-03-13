import requests
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.shortcuts import redirect, get_object_or_404
from django.utils import timezone

from . import models
from import_export.admin import ExportActionMixin
from django.utils.html import format_html
from django.db import transaction
from django.urls import path
from django.contrib import messages

from .models import TopUpRequest


# Register your models here.
class CustomUserAdmin(UserAdmin):
    list_display = ['first_name', 'last_name', 'username', 'email', 'wallet', 'phone', 'status']
    search_fields = ['username', 'first_name', 'last_name', 'phone']

    fieldsets = (
        *UserAdmin.fieldsets,
        (
            'Other Personal info',
            {
                'fields': (
                    'phone', 'wallet', 'status'
                )
            }
        )
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide', ),
            'fields': ('username', 'password1', 'password2', 'wallet')
        }),)
    

class IShareBundleTransactionAdmin(admin.ModelAdmin):
    list_display = ['user', 'bundle_number', 'offer', 'reference', 'transaction_status', 'transaction_date']
    search_fields = ['reference', 'bundle_number', 'user__username',]


class MTNTransactionAdmin(admin.ModelAdmin):
    list_display = ['user', 'bundle_number', 'offer', 'reference', 'transaction_status', 'transaction_date']
    search_fields = ['reference', 'bundle_number', 'user__username']


class PaymentAdmin(admin.ModelAdmin):
    list_display = ['user', 'reference', 'transaction_date', 'amount']


class TopUpRequestAdmin(admin.ModelAdmin):
    list_display = ['user', 'reference', 'amount', 'date', 'status', 'credit_user_button']
    list_filter = ['status', 'date']
    actions = ['credit_selected_users']

    def credit_user_button(self, obj):
        if not obj.status:
            return format_html(
                '<a class="button" href="{}" style="padding: 5px 10px; background-color: #28a745; color: white; border-radius: 3px; text-decoration: none;">Credit User</a>',
                f'credit/{obj.pk}/'
            )
        return "Already Credited"

    credit_user_button.short_description = 'Action'
    credit_user_button.allow_tags = True

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('credit/<int:topup_id>/', self.admin_site.admin_view(self.credit_user), name='credit-user'),
        ]
        return custom_urls + urls

    def credit_user(self, request, topup_id, *args, **kwargs):
        topup_request = get_object_or_404(TopUpRequest, pk=topup_id)

        if topup_request.status:
            self.message_user(request, "This transaction has already been credited.", level=messages.WARNING)
            return redirect('..')

        try:
            with transaction.atomic():
                user = topup_request.user
                user.wallet += topup_request.amount
                user.save()

                topup_request.status = True
                topup_request.credited_at = timezone.now()
                topup_request.save()
                sms_headers = {
                    'Authorization': 'Bearer 2069|fMiymkKVytFt84w8GNM8vq0zF2UtakVaNZT1RUVWfd642028',
                    'Content-Type': 'application/json'
                }

                sms_url = 'https://webapp.usmsgh.com/api/sms/send'
                sms_message = f"Your wallet has been credited with GHS{topup_request.amount}."

                sms_body = {
                    'recipient': f"233{user.phone}",
                    'sender_id': 'DANWELSTORE',
                    'message': sms_message
                }
                response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
                print(response.text)
                self.message_user(request, f"Successfully credited {topup_request.amount} to {user.username}.",
                                  level=messages.SUCCESS)
        except Exception as e:
            self.message_user(request, f"An error occurred: {str(e)}", level=messages.ERROR)

        return redirect('..')

    def credit_selected_users(self, request, queryset):
        pending_requests = queryset.filter(status=False)
        if not pending_requests.exists():
            self.message_user(request, "No pending transactions selected.", level=messages.WARNING)
            return

        try:
            with transaction.atomic():
                # Group pending requests by user to optimize wallet updates
                user_requests = {}
                for request_obj in pending_requests:
                    user = request_obj.user
                    if user in user_requests:
                        user_requests[user].append(request_obj)
                    else:
                        user_requests[user] = [request_obj]

                for user, requests_list in user_requests.items():
                    total_amount = sum(req.amount for req in requests_list)
                    user.wallet += total_amount
                    user.save()

                    for req in requests_list:
                        req.status = True
                        req.credited_at = timezone.now()
                        req.save()

                self.message_user(request, f"Successfully credited {pending_requests.count()} transactions.",
                                  level=messages.SUCCESS)
        except Exception as e:
            self.message_user(request, f"An error occurred: {str(e)}", level=messages.ERROR)

    credit_selected_users.short_description = "Credit selected top-up requests"


class ProductImageInline(admin.TabularInline):  # or admin.StackedInline
    model = models.ProductImage
    extra = 4  # Set the number of empty forms to display


class ProductAdmin(admin.ModelAdmin):
    inlines = [ProductImageInline]
    search_fields = ['name']


admin.site.register(models.CustomUser, CustomUserAdmin)
admin.site.register(models.IShareBundleTransaction, IShareBundleTransactionAdmin)
admin.site.register(models.MTNTransaction, MTNTransactionAdmin)
admin.site.register(models.IshareBundlePrice)
admin.site.register(models.MTNBundlePrice)
admin.site.register(models.Payment, PaymentAdmin)
admin.site.register(models.AdminInfo)
admin.site.register(models.TopUpRequest, TopUpRequestAdmin)
admin.site.register(models.AgentIshareBundlePrice)
admin.site.register(models.AgentMTNBundlePrice)
admin.site.register(models.SuperAgentIshareBundlePrice)
admin.site.register(models.AFARegistration)
admin.site.register(models.BigTimeTransaction)
admin.site.register(models.SuperAgentMTNBundlePrice)
admin.site.register(models.BigTimeBundlePrice)
admin.site.register(models.AgentBigTimeBundlePrice)
admin.site.register(models.SuperAgentBigTimeBundlePrice)
admin.site.register(models.TelecelBundlePrice)
admin.site.register(models.AgentTelecelBundlePrice)
admin.site.register(models.SuperAgentTelecelBundlePrice)
admin.site.register(models.TelecelTransaction)
admin.site.register(models.Announcement)


#########################################################################
admin.site.register(models.Category)
admin.site.register(models.Product, ProductAdmin)
admin.site.register(models.Cart)
admin.site.register(models.OrderItem)
admin.site.register(models.Order)
admin.site.register(models.Brand)
admin.site.register(models.ProductImage),
