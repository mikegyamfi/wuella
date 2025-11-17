import hashlib
import hmac
import json
import random
from datetime import datetime, timedelta
from decimal import Decimal
from time import sleep

import pandas as pd
from decouple import config
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, Permission
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponseRedirect, HttpResponse
import requests
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from intel_app import models, forms, helper
from intel_app.views import paystack_initialize


def shop_home_collections(request):
    general_categories = models.Category.objects.all().order_by('name')
    context = {'general_categories': general_categories}
    return render(request, 'shop/collections.html', context=context)


def collection_products(request, category_name):
    print(category_name)
    print(models.Category.objects.filter(name=category_name).exists())
    if models.Category.objects.filter(name=category_name).exists():
        collection = models.Category.objects.get(name=category_name)
        products = models.Product.objects.filter(category=collection)
        category_name = models.Category.objects.filter(name=category_name).first()
        context = {
            'products': products,
            'category_name': category_name
        }
        return render(request, 'shop/collection_products.html', context=context)
    else:
        messages.warning(request, "Link is broken")
        return redirect('shop')


def product_details(request, category_name, prod_name):
    if models.Category.objects.filter(name=category_name):
        if models.Product.objects.filter(name=prod_name):
            product = models.Product.objects.get(name=prod_name)
            product_images = models.ProductImage.objects.filter(product=product)
            main_image = product_images.first()
            category = models.Category.objects.get(name=category_name)
            context = {
                'product': product,
                'cat_name': category.name,
                'images': product_images,
                'main_image': main_image,
                'current_date': datetime.now().date()
            }
            return render(request, 'shop/product_detail.html', context=context)
        else:
            messages.error(request, 'Something went wrong')
            return redirect('shop')
    else:
        messages.error(request, "No such category found")
        return redirect('shop')


@login_required(login_url='login')
def add_to_cart(request):
    if request.method == 'POST':
        if request.user.is_authenticated:
            prod_id = int(request.POST.get('product_id'))
            product_check = models.Product.objects.get(id=prod_id)
            if product_check:
                if models.Cart.objects.filter(user=request.user.id, product_id=prod_id):
                    return JsonResponse({'status': "Item already in Cart"})
                else:
                    product_qty = int(request.POST.get('product_qty'))
                    if product_check.quantity >= product_qty:
                        models.Cart.objects.create(user=request.user, product_id=prod_id, product_qty=product_qty)
                        return JsonResponse({'status': "Product added to Cart"})
                    else:
                        return JsonResponse(
                            {'status': "Only " + str(product_check.quantity) + " of this product is available"})
            else:
                return JsonResponse({'status': "Something went wrong"})
        else:
            return JsonResponse({'status': "Login to continue"})
    return redirect('home')


@login_required(login_url='login')
@login_required(login_url='login')
def viewcart(request):
    cart = models.Cart.objects.filter(user=request.user)
    context = {'cart': cart}
    return render(request, 'shop/cart.html', context)


@login_required(login_url='login')
def update_cart(request):
    if request.method == 'POST':
        prod_id = int(request.POST.get('product_id'))
        if models.Cart.objects.filter(user=request.user, product_id=prod_id):
            product = models.Product.objects.get(id=prod_id)
            product_qty = int(request.POST.get('product_qty'))
            if product.quantity < product_qty:
                return JsonResponse({'status': f'Only {product.quantity} of this product is available'})
            cart = models.Cart.objects.get(product_id=prod_id, user=request.user)
            cart.product_qty = product_qty
            cart.save()
            return JsonResponse({'status': 'Item quantity updated'})
    return redirect('shop')


@login_required(login_url='login')
def delete_cart_item(request):
    if request.method == 'POST':
        prod_id = int(request.POST.get('product_id'))
        if models.Cart.objects.filter(user=request.user, product_id=prod_id):
            cart_item = models.Cart.objects.get(product_id=prod_id, user=request.user)
            cart_item.delete()
        return JsonResponse({'status': 'Item removed from cart'})
    return redirect('cart')


@login_required(login_url='login')
def checkout(request):
    user = models.CustomUser.objects.get(id=request.user.id)
    cart_items = models.Cart.objects.filter(user=request.user)

    # Check if cart is empty
    if not cart_items.exists():
        messages.warning(request, "Your cart is empty.")
        return redirect('shop')

    # 1. Calculate Total (Decimal Safe)
    cart_total_price = Decimal("0.00")
    for item in cart_items:
        # Stock Check
        if item.product_qty > item.product.quantity:
            messages.error(request, f"Item {item.product.name} is out of stock or low quantity.")
            return redirect('cart')

        price = Decimal(str(item.product.selling_price))
        qty = Decimal(item.product_qty)
        cart_total_price += price * qty

    if request.method == 'POST':
        form = forms.OrderDetailsForm(request.POST)
        payment_mode = request.POST.get('payment_mode')

        if form.is_valid():
            # ---------------- OPTION A: WALLET PAYMENT ----------------
            if payment_mode == "Wallet":
                if user.wallet is None or user.wallet < cart_total_price:
                    messages.error(request, "Insufficient wallet balance.")
                    return redirect('checkout')

                try:
                    with transaction.atomic():
                        # 1. Deduct Money
                        user.wallet -= cart_total_price
                        user.save()

                        # 2. Create Order AND Finalize (Deduct Stock, Clear Cart)
                        _create_order_and_items(
                            request, form, cart_items, cart_total_price,
                            "Wallet", "Completed", finalize=True
                        )

                    messages.success(request, "Order placed successfully via Wallet!")
                    return redirect('orders')

                except Exception as e:
                    print(e)
                    messages.error(request, "Error processing wallet payment.")
                    return redirect('checkout')

            # ---------------- OPTION B: PAYSTACK PAYMENT ----------------
            elif payment_mode == "Paystack":
                ref = helper.ref_generator()

                try:
                    # 1. Create Order but DO NOT Finalize (Keep Cart, Keep Stock)
                    # We set status to 'Pending Payment'
                    order = _create_order_and_items(
                        request, form, cart_items, cart_total_price,
                        "Paystack", "Pending Payment", ref=ref, finalize=False
                    )

                    # 2. Initialize Paystack
                    amount_pesewas = int(cart_total_price * 100)
                    meta = {
                        "purpose": "shop_order",
                        "order_tracking_number": order.tracking_number,
                        "user_id": user.id
                    }

                    init_data = paystack_initialize(
                        email=user.email,
                        amount_pesewas=amount_pesewas,
                        reference=ref,
                        metadata=meta
                    )
                    return redirect(init_data['data']['authorization_url'])

                except Exception as e:
                    print(e)
                    # Since we didn't finalize, the cart and stock are safe.
                    # We can optionally delete the pending order here if we want,
                    # or leave it as an "Abandoned Cart" record.
                    messages.error(request, "Error initializing Paystack. Please try again.")
                    return redirect('checkout')

            else:
                messages.error(request, "Please select a valid payment method.")
                return redirect('checkout')
        else:
            messages.error(request, "Invalid details provided.")
            return redirect('checkout')

    # GET Logic
    form = forms.OrderDetailsForm(initial={
        'full_name': f"{request.user.first_name} {request.user.last_name}",
        'email': request.user.email,
        'phone_number': request.user.phone
    })

    context = {
        'cart_items': cart_items,
        'total_price': cart_total_price,
        'form': form,
        'wallet': user.wallet
    }
    return render(request, 'shop/checkout.html', context)


# Helper function to avoid repeating code
def _create_order_and_items(request, form, cart_items, total_price, mode, status, ref=None, finalize=False):
    if not ref:
        ref = 'DW' + str(random.randint(11111111, 99999999))

    order = form.save(commit=False)

    # Fallback logic for empty fields
    if not order.email:
        order.email = request.user.email
    if not order.phone:
        order.phone = request.user.phone

    order.user = request.user
    order.total_price = float(total_price)
    order.payment_mode = mode
    order.tracking_number = ref
    order.status = status
    order.save()

    # Create Order Items (Snapshot)
    for item in cart_items:
        models.OrderItem.objects.create(
            order=order,
            product=item.product,
            tracking_number=ref,
            price=item.product.selling_price,
            quantity=item.product_qty
        )

        # ONLY deduct stock if finalizing immediately (Wallet)
        if finalize:
            item.product.quantity -= item.product_qty
            item.product.save()

    # ONLY clear cart and send SMS if finalizing immediately (Wallet)
    if finalize:
        cart_items.delete()

        # Send SMS
        sms_headers = {
            'Authorization': 'Bearer 2069|fMiymkKVytFt84w8GNM8vq0zF2UtakVaNZT1RUVWfd642028',
            'Content-Type': 'application/json'
        }
        sms_url = 'https://webapp.usmsgh.com/api/sms/send'
        sms_message = f"Order Placed Successfully\nYour order {order.tracking_number} is processed.\nThank you for shopping with DanWelStore Gh"
        sms_body = {
            'recipient': f"233{order.phone}",
            'sender_id': 'DANWEL',
            'message': sms_message
        }
        try:
            requests.post(sms_url, json=sms_body, headers=sms_headers, timeout=5)
        except:
            pass

    return order


@login_required(login_url='login')
def orders(request):
    # Only show orders that are NOT pending payment
    all_orders = models.Order.objects.filter(user=request.user) \
        .exclude(status='Pending Payment') \
        .order_by('-created_at')
    context = {'orders': all_orders}
    return render(request, 'shop/order-page.html', context)


@login_required(login_url='login')
def view_order(request, t_no):
    if request.user.is_superuser:
        order = models.Order.objects.filter(tracking_number=t_no).first()
    else:
        order = models.Order.objects.filter(tracking_number=t_no).filter(user=request.user).first()
    order_items = models.OrderItem.objects.filter(order=order)
    context = {'order_items': order_items, 'order': order}
    return render(request, 'shop/view_order.html', context)


@login_required(login_url='login')
def admin_orders(request):
    if request.user.is_superuser or request.user.is_staff:
        # 1. Start with all orders
        orders_list = models.Order.objects.all().order_by('-created_at')

        # 2. Get Filter Parameters from URL
        status_filter = request.GET.get('status')
        payment_mode_filter = request.GET.get('payment_mode')
        search_query = request.GET.get('search')

        # 3. Apply Filters if they exist
        if status_filter:
            orders_list = orders_list.filter(status=status_filter)

        if payment_mode_filter:
            orders_list = orders_list.filter(payment_mode=payment_mode_filter)

        if search_query:
            # Search by Tracking Number OR Customer Name OR Phone
            orders_list = orders_list.filter(
                Q(tracking_number__icontains=search_query) |
                Q(full_name__icontains=search_query) |
                Q(phone__icontains=search_query)
            )

        # 4. Pagination (Show 20 orders per page)
        paginator = Paginator(orders_list, 20)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        context = {
            'orders': page_obj,  # Pass the paginated object, not the full list
            'admin': 'Yes',
            # Pass current filters back to template so they stay selected
            'current_status': status_filter,
            'current_payment': payment_mode_filter,
            'current_search': search_query
        }
        return render(request, 'shop/order-page.html', context)
    else:
        messages.error(request, "Access Denied")
        return redirect('shop')


def product_list_ajax(request):
    products = models.Product.objects.filter().values_list('name', flat=True)
    product_list = list(products)

    return JsonResponse({'products': product_list}, safe=False)


def search_product(request):
    if request.method == 'POST':
        product_searched = request.POST.get('prod_search')
        if product_searched == "":
            return redirect(request.META.get('HTTP_REFERER'))
        else:
            product = models.Product.objects.filter(name__contains=product_searched).first()

            if product:
                return redirect(product.category.name + '/' + product.name + '/details')
            else:
                messages.info(request, "No product matched your search")
                return redirect(request.META.get('HTTP_REFERER'))
    return redirect(request.META.get('HTTP_REFERER'))


def change_order_status(request, t_no, stat):
    order = models.Order.objects.filter(tracking_number=t_no).first()
    if request.user.is_superuser:
        if stat == "out":
            order.status = "Out for Delivery"
            order.save()
            sms_headers = {
                'Authorization': 'Bearer 2069|fMiymkKVytFt84w8GNM8vq0zF2UtakVaNZT1RUVWfd642028',
                'Content-Type': 'application/json'
            }

            sms_url = 'https://webapp.usmsgh.com/api/sms/send'
            sms_message = f"Hello {order.full_name},\nYour Order with tracking number {t_no} is out for delivery. You will receive a call from our delivery contact soon. Thank You"

            sms_body = {
                'recipient': f"233{order.phone}",
                'sender_id': 'DANWELSTORE',
                'message': sms_message
            }
            try:
                response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
                print(response.text)
            except:
                print("Could not send sms message")
        elif stat == "Completed":
            order.status = "Completed"
            order.save()
            sms_headers = {
                'Authorization': 'Bearer 2069|fMiymkKVytFt84w8GNM8vq0zF2UtakVaNZT1RUVWfd642028',
                'Content-Type': 'application/json'
            }

            sms_url = 'https://webapp.usmsgh.com/api/sms/send'
            sms_message = f"Hello {order.full_name},\nYour Order with tracking number {t_no} has been delivered successfully. Thank you for your patronage. Keep Shopping!"

            sms_body = {
                'recipient': f"233{order.phone}",
                'sender_id': 'DANWELSTORE',
                'message': sms_message
            }
            try:
                response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
                print(response.text)
            except:
                print("Could not send sms message")
        elif stat == "Canceled":
            order.status = "Canceled"
            order.save()
            sms_headers = {
                'Authorization': 'Bearer 2069|fMiymkKVytFt84w8GNM8vq0zF2UtakVaNZT1RUVWfd642028',
                'Content-Type': 'application/json'
            }

            sms_url = 'https://webapp.usmsgh.com/api/sms/send'
            sms_message = f"Hello {order.full_name},\nYour Order with tracking number {t_no} has been canceled due to some reasons. Thank you for your patronage. Keep Shopping!"

            sms_body = {
                'recipient': f"233{order.phone}",
                'sender_id': 'DANWELSTORE',
                'message': sms_message
            }
            try:
                response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
                print(response.text)
            except:
                print("Could not send sms message")
        messages.success(request, "Order Status Changed")
        return redirect('view_order', t_no=t_no)
    else:
        messages.error(request, "Access Denied")
        return redirect('view_order', t_no=t_no)


@login_required(login_url='login')
def clear_pending_orders(request):
    if request.user.is_superuser or request.user.is_staff:
        if request.method == "POST":
            # OPTION 1: Delete ALL Pending orders immediately
            # deleted_count, _ = models.Order.objects.filter(status="Pending Payment").delete()

            # OPTION 2 (SAFER): Only delete Pending orders created more than 30 mins ago
            # This prevents deleting an order while a user is currently on the Paystack page
            time_threshold = timezone.now() - timedelta(minutes=30)
            deleted_count, _ = models.Order.objects.filter(
                status="Pending Payment",
                created_at__lt=time_threshold
            ).delete()

            if deleted_count > 0:
                messages.success(request, f"Successfully cleared {deleted_count} abandoned orders.")
            else:
                messages.info(request, "No old pending orders found to clear.")

            return redirect('admin_orders')
        return None
    else:
        messages.error(request, "Access Denied")
        return redirect('shop')


