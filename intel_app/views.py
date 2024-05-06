import json
from datetime import datetime

import pandas as pd
from decouple import config
from django.contrib.auth.forms import PasswordResetForm
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponseRedirect
import requests
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.csrf import csrf_exempt

from . import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from . import helper, models
from .forms import UploadFileForm
from .models import CustomUser


# Create your views here.
def home(request):
    return render(request, "layouts/index.html")


def services(request):
    return render(request, "layouts/services.html")


def pay_with_wallet(request):
    if request.method == "POST":

        user = models.CustomUser.objects.get(id=request.user.id)
        phone_number = request.POST.get("phone")
        amount = request.POST.get("amount")
        reference = request.POST.get("reference")
        if user.wallet is None:
            return JsonResponse({'status': f'Your wallet balance is low. Contact the admin to recharge.'})
        elif user.wallet <= 0 or user.wallet < float(amount):
            return JsonResponse({'status': f'Your wallet balance is low. Contact the admin to recharge.'})
        print(phone_number)
        print(amount)
        print(reference)
        if user.status == "User":
            bundle = models.IshareBundlePrice.objects.get(price=float(amount)).bundle_volume
        elif user.status == "Agent":
            bundle = models.AgentIshareBundlePrice.objects.get(price=float(amount)).bundle_volume
        elif user.status == "Super Agent":
            bundle = models.SuperAgentIshareBundlePrice.objects.get(price=float(amount)).bundle_volume
        else:
            bundle = models.IshareBundlePrice.objects.get(price=float(amount)).bundle_volume

        print(bundle)
        send_bundle_response = helper.send_bundle(request.user, phone_number, bundle, reference)
        try:
            data = send_bundle_response.json()
            print(data)
        except:
            return JsonResponse({'status': f'Something went wrong'})

        sms_headers = {
            'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
            'Content-Type': 'application/json'
        }

        sms_url = 'https://webapp.usmsgh.com/api/sms/send'
        if send_bundle_response.status_code == 200:
            if data["code"] == "0000":
                new_transaction = models.IShareBundleTransaction.objects.create(
                    user=request.user,
                    bundle_number=phone_number,
                    offer=f"{bundle}MB",
                    reference=reference,
                    transaction_status="Completed"
                )
                new_transaction.save()
                user.wallet -= float(amount)
                user.save()
                receiver_message = f"Your bundle purchase has been completed successfully. {bundle}MB has been credited to you by {request.user.phone}.\nReference: {reference}\n"
                sms_message = f"Hello @{request.user.username}. Your bundle purchase has been completed successfully. {bundle}MB has been credited to {phone_number}.\nReference: {reference}\nCurrent Wallet Balance: {user.wallet}\nThank you for using DanWel Store GH.\n\nThe DanWel Store GH"

                num_without_0 = phone_number[1:]
                print(num_without_0)
                # receiver_body = {
                #     'recipient': f"233{num_without_0}",
                #     'sender_id': 'DANWELSTORE',
                #     'message': receiver_message
                # }
                #
                # response = requests.request('POST', url=sms_url, params=receiver_body, headers=sms_headers)
                # print(response.text)

                sms_body = {
                    'recipient': f"233{request.user.phone}",
                    'sender_id': 'DANWELSTORE',
                    'message': sms_message
                }

                response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)

                print(response.text)

                # response1 = requests.get(
                #     f"https://sms.arkesel.com/sms/api?action=send-sms&api_key=OnBuSjBXc1pqN0xrQXIxU1A=&to=0{request.user.phone}&from=DANWELSTORE&sms={sms_message}")
                # print(response1.text)
                #
                # response2 = requests.get(
                #     f"https://sms.arkesel.com/sms/api?action=send-sms&api_key=OnBuSjBXc1pqN0xrQXIxU1A=&to={phone_number}&from=DANWELSTORE&sms={receiver_message}")
                # print(response2.text)

                return JsonResponse({'status': 'Transaction Completed Successfully', 'icon': 'success'})
            else:
                new_transaction = models.IShareBundleTransaction.objects.create(
                    user=request.user,
                    bundle_number=phone_number,
                    offer=f"{bundle}MB",
                    reference=reference,
                    transaction_status="Failed"
                )
                new_transaction.save()
                return JsonResponse({'status': 'Something went wrong', 'icon': 'error'})
    return redirect('airtel-tigo')


@login_required(login_url='login')
def airtel_tigo(request):
    user = models.CustomUser.objects.get(id=request.user.id)
    status = user.status
    form = forms.IShareBundleForm(status)
    reference = helper.ref_generator()
    user_email = request.user.email
    if request.method == "POST":
        form = forms.IShareBundleForm(data=request.POST, status=status)
        payment_reference = request.POST.get("reference")
        amount_paid = request.POST.get("amount")
        new_payment = models.Payment.objects.create(
            user=request.user,
            reference=payment_reference,
            amount=amount_paid,
            transaction_date=datetime.now(),
            transaction_status="Completed"
        )
        new_payment.save()
        print("payment saved")
        print("form valid")
        phone_number = request.POST.get("phone")
        offer = request.POST.get("amount")
        print(offer)
        bundle = models.IshareBundlePrice.objects.get(
            price=float(offer)).bundle_volume if user.status == "User" else models.AgentIshareBundlePrice.objects.get(
            price=float(offer)).bundle_volume

        new_transaction = models.IShareBundleTransaction.objects.create(
            user=request.user,
            bundle_number=phone_number,
            offer=f"{bundle}MB",
            reference=payment_reference,
            transaction_status="Pending"
        )
        print("created")
        new_transaction.save()

        print("===========================")
        print(phone_number)
        print(bundle)
        send_bundle_response = helper.send_bundle(request.user, phone_number, bundle, reference)
        data = send_bundle_response.json()

        print(data)

        sms_headers = {
            'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
            'Content-Type': 'application/json'
        }

        sms_url = 'https://webapp.usmsgh.com/api/sms/send'

        if send_bundle_response.status_code == 200:
            if data["code"] == "0000":
                transaction_to_be_updated = models.IShareBundleTransaction.objects.get(reference=payment_reference)
                print("got here")
                print(transaction_to_be_updated.transaction_status)
                transaction_to_be_updated.transaction_status = "Completed"
                transaction_to_be_updated.save()
                print(request.user.phone)
                print("***********")
                receiver_message = f"Your bundle purchase has been completed successfully. {bundle}MB has been credited to you by {request.user.phone}.\nReference: {payment_reference}\n"
                sms_message = f"Hello @{request.user.username}. Your bundle purchase has been completed successfully. {bundle}MB has been credited to {phone_number}.\nReference: {payment_reference}\nThank you for using DanWel Store GH.\n\nThe DanWel Store GH"

                num_without_0 = phone_number[1:]
                print(num_without_0)
                receiver_body = {
                    'recipient': f"233{num_without_0}",
                    'sender_id': 'DANWELSTORE',
                    'message': receiver_message
                }

                response = requests.request('POST', url=sms_url, params=receiver_body, headers=sms_headers)
                print(response.text)

                sms_body = {
                    'recipient': f"233{request.user.phone}",
                    'sender_id': 'DANWELSTORE',
                    'message': sms_message
                }

                response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)

                print(response.text)

                return JsonResponse({'status': 'Transaction Completed Successfully', 'icon': 'success'})
            else:
                transaction_to_be_updated = models.IShareBundleTransaction.objects.get(reference=payment_reference)
                transaction_to_be_updated.transaction_status = "Failed"
                new_transaction.save()
                sms_message = f"Hello @{request.user.username}. Something went wrong with your transaction. Contact us for enquiries.\nBundle: {bundle}MB\nPhone Number: {phone_number}.\nReference: {payment_reference}\nThank you for using DanWel Store GH.\n\nThe DanWel Store GH"

                sms_body = {
                    'recipient': f"233{request.user.phone}",
                    'sender_id': 'DANWELSTORE',
                    'message': sms_message
                }
                response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
                print(response.text)
                # r_sms_url = f"https://sms.arkesel.com/sms/api?action=send-sms&api_key=UmpEc1JzeFV4cERKTWxUWktqZEs&to={phone_number}&from=DanWel Store GH&sms={receiver_message}"
                # response = requests.request("GET", url=r_sms_url)
                # print(response.text)
                return JsonResponse({'status': 'Something went wrong', 'icon': 'error'})
        else:
            transaction_to_be_updated = models.IShareBundleTransaction.objects.get(reference=payment_reference)
            transaction_to_be_updated.transaction_status = "Failed"
            new_transaction.save()
            sms_message = f"Hello @{request.user.username}. Something went wrong with your transaction. Contact us for enquiries.\nBundle: {bundle}MB\nPhone Number: {phone_number}.\nReference: {payment_reference}\nThank you for using DanWel Store GH.\n\nThe DanWel Store GH"

            sms_body = {
                'recipient': f'233{request.user.phone}',
                'sender_id': 'DANWELSTORE',
                'message': sms_message
            }

            response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)

            print(response.text)
            return JsonResponse({'status': 'Something went wrong', 'icon': 'error'})
    user = models.CustomUser.objects.get(id=request.user.id)
    context = {"form": form, "ref": reference, "email": user_email, "wallet": 0 if user.wallet is None else user.wallet}
    return render(request, "layouts/services/at.html", context=context)


def mtn_pay_with_wallet(request):
    if request.method == "POST":
        user = models.CustomUser.objects.get(id=request.user.id)
        phone_number = request.POST.get("phone")
        amount = request.POST.get("amount")
        reference = request.POST.get("reference")
        print(phone_number)
        print(amount)
        print(reference)
        sms_headers = {
            'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
            'Content-Type': 'application/json'
        }

        sms_url = 'https://webapp.usmsgh.com/api/sms/send'
        admin = models.AdminInfo.objects.filter().first().phone_number

        if user.wallet is None:
            return JsonResponse(
                {'status': f'Your wallet balance is low. Contact the admin to recharge. Admin Contact Info: 0{admin}'})
        elif user.wallet <= 0 or user.wallet < float(amount):
            return JsonResponse(
                {'status': f'Your wallet balance is low. Contact the admin to recharge. Admin Contact Info: 0{admin}'})
        if user.status == "User":
            bundle = models.MTNBundlePrice.objects.get(price=float(amount)).bundle_volume
        elif user.status == "Agent":
            bundle = models.AgentMTNBundlePrice.objects.get(price=float(amount)).bundle_volume
        elif user.status == "Super Agent":
            bundle = models.SuperAgentMTNBundlePrice.objects.get(price=float(amount)).bundle_volume
        else:
            bundle = models.MTNBundlePrice.objects.get(price=float(amount)).bundle_volume
        print(bundle)
        sms_message = f"An order has been placed. {bundle}MB for {phone_number}"
        new_mtn_transaction = models.MTNTransaction.objects.create(
            user=request.user,
            bundle_number=phone_number,
            offer=f"{bundle}MB",
            reference=reference,
        )
        new_mtn_transaction.save()
        user.wallet -= float(amount)
        user.save()
        sms_body = {
            'recipient': f"233{admin}",
            'sender_id': 'DANWELSTORE',
            'message': sms_message
        }
        # response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
        # print(response.text)
        return JsonResponse({'status': "Your transaction will be completed shortly", 'icon': 'success'})
    return redirect('mtn')


def telecel_pay_with_wallet(request):
    if request.method == "POST":
        user = models.CustomUser.objects.get(id=request.user.id)
        phone = user.phone
        phone_number = request.POST.get("phone")
        amount = request.POST.get("amount")
        reference = request.POST.get("reference")
        print(phone_number)
        print(amount)
        print(reference)
        # sms_headers = {
        #     'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
        #     'Content-Type': 'application/json'
        # }
        #
        # sms_url = 'https://webapp.usmsgh.com/api/sms/send'
        # admin = models.AdminInfo.objects.filter().first().phone_number

        if user.wallet is None:
            return JsonResponse({'status': f'Your wallet balance is low. Contact the admin to recharge.'})
        elif user.wallet <= 0 or user.wallet < float(amount):
            return JsonResponse({'status': f'Your wallet balance is low. Contact the admin to recharge.'})
        if user.status == "User":
            bundle = models.TelecelBundlePrice.objects.get(price=float(amount)).bundle_volume
        elif user.status == "Agent":
            bundle = models.AgentTelecelBundlePrice.objects.get(price=float(amount)).bundle_volume
        elif user.status == "Super Agent":
            bundle = models.SuperAgentTelecelBundlePrice.objects.get(price=float(amount)).bundle_volume
        else:
            bundle = models.TelecelBundlePrice.objects.get(price=float(amount)).bundle_volume

        print(bundle)
        sms_message = f"An order has been placed. {bundle}MB for {phone_number}"
        new_telecel_transaction = models.TelecelTransaction.objects.create(
            user=request.user,
            bundle_number=phone_number,
            offer=f"{bundle}MB",
            reference=reference,
        )
        new_telecel_transaction.save()
        user.wallet -= float(amount)
        user.save()
        # sms_body = {
        #     'recipient': "233540975553",
        #     'sender_id': 'DANWELSTORE',
        #     'message': sms_message
        # }
        # response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
        # print(response.text)
        return JsonResponse({'status': "Your transaction will be completed shortly", 'icon': 'success'})
    return redirect('telecel')


@login_required(login_url='login')
def big_time_pay_with_wallet(request):
    if request.method == "POST":
        user = models.CustomUser.objects.get(id=request.user.id)
        phone_number = request.POST.get("phone")
        amount = request.POST.get("amount")
        reference = request.POST.get("reference")
        print(phone_number)
        print(amount)
        print(reference)
        if user.wallet is None:
            return JsonResponse(
                {'status': f'Your wallet balance is low. Contact the admin to recharge.'})
        elif user.wallet <= 0 or user.wallet < float(amount):
            return JsonResponse(
                {'status': f'Your wallet balance is low. Contact the admin to recharge.'})
        if user.status == "User":
            bundle = models.BigTimeBundlePrice.objects.get(price=float(amount)).bundle_volume
        elif user.status == "Agent":
            bundle = models.AgentBigTimeBundlePrice.objects.get(price=float(amount)).bundle_volume
        elif user.status == "Super Agent":
            bundle = models.SuperAgentBigTimeBundlePrice.objects.get(price=float(amount)).bundle_volume
        else:
            bundle = models.BigTimeBundlePrice.objects.get(price=float(amount)).bundle_volume
        print(bundle)
        new_mtn_transaction = models.BigTimeTransaction.objects.create(
            user=request.user,
            bundle_number=phone_number,
            offer=f"{bundle}MB",
            reference=reference,
        )
        new_mtn_transaction.save()
        user.wallet -= float(amount)
        user.save()
        return JsonResponse({'status': "Your transaction will be completed shortly", 'icon': 'success'})
    return redirect('big_time')


@login_required(login_url='login')
def mtn(request):
    user = models.CustomUser.objects.get(id=request.user.id)
    phone = user.phone
    status = user.status
    form = forms.MTNForm(status=status)
    reference = helper.ref_generator()
    user_email = request.user.email
    if request.method == "POST":
        payment_reference = request.POST.get("reference")
        amount_paid = request.POST.get("amount")
        new_payment = models.Payment.objects.create(
            user=request.user,
            reference=payment_reference,
            amount=amount_paid,
            transaction_date=datetime.now(),
            transaction_status="Completed"
        )
        new_payment.save()
        phone_number = request.POST.get("phone")
        offer = request.POST.get("amount")

        if user.status == "User":
            bundle = models.MTNBundlePrice.objects.get(price=float(offer)).bundle_volume
        elif user.status == "Agent":
            bundle = models.AgentMTNBundlePrice.objects.get(price=float(offer)).bundle_volume

        new_mtn_transaction = models.MTNTransaction.objects.create(
            user=request.user,
            bundle_number=phone_number,
            offer=f"{bundle}MB",
            reference=payment_reference,

        )
        new_mtn_transaction.save()
        sms_headers = {
            'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
            'Content-Type': 'application/json'
        }

        sms_url = 'https://webapp.usmsgh.com/api/sms/send'
        sms_message = f"An order has been placed. {bundle}MB for {phone_number}"

        sms_body = {
            'recipient': "233540975553",
            'sender_id': 'DANWELSTORE',
            'message': sms_message
        }
        response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
        print(response.text)
        return JsonResponse({'status': "Your transaction will be completed shortly", 'icon': 'success'})
    user = models.CustomUser.objects.get(id=request.user.id)
    phone_num = user.phone

    context = {'form': form, 'phone_num': phone_num,
               "ref": reference, "email": user_email, "wallet": 0 if user.wallet is None else user.wallet}
    return render(request, "layouts/services/mtn.html", context=context)


@login_required(login_url='login')
def telecel(request):
    user = models.CustomUser.objects.get(id=request.user.id)
    phone = user.phone
    status = user.status
    form = forms.TelecelForm(status=status)
    reference = helper.ref_generator()
    user_email = request.user.email
    if request.method == "POST":
        payment_reference = request.POST.get("reference")
        amount_paid = request.POST.get("amount")
        new_payment = models.Payment.objects.create(
            user=request.user,
            reference=payment_reference,
            amount=amount_paid,
            transaction_date=datetime.now(),
            transaction_status="Completed"
        )
        new_payment.save()
        phone_number = request.POST.get("phone")
        offer = request.POST.get("amount")

        if user.status == "User":
            bundle = models.TelecelBundlePrice.objects.get(price=float(offer)).bundle_volume
        elif user.status == "Agent":
            bundle = models.AgentTelecelBundlePrice.objects.get(price=float(offer)).bundle_volume

        new_mtn_transaction = models.MTNTransaction.objects.create(
            user=request.user,
            bundle_number=phone_number,
            offer=f"{bundle}MB",
            reference=payment_reference,

        )
        new_mtn_transaction.save()
        sms_headers = {
            'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
            'Content-Type': 'application/json'
        }

        sms_url = 'https://webapp.usmsgh.com/api/sms/send'
        sms_message = f"An order has been placed. {bundle}MB for {phone_number}"

        sms_body = {
            'recipient': "233540975553",
            'sender_id': 'DANWELSTORE',
            'message': sms_message
        }
        response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
        print(response.text)
        return JsonResponse({'status': "Your transaction will be completed shortly", 'icon': 'success'})
    user = models.CustomUser.objects.get(id=request.user.id)
    phone_num = user.phone

    context = {'form': form, 'phone_num': phone_num,
               "ref": reference, "email": user_email, "wallet": 0 if user.wallet is None else user.wallet}
    return render(request, "layouts/services/voda.html", context=context)


@login_required(login_url='login')
def afa_registration(request):
    user = models.CustomUser.objects.get(id=request.user.id)
    reference = helper.ref_generator()
    db_user_id = request.user.id
    price = models.AdminInfo.objects.filter().first().afa_price
    user_email = request.user.email
    print(price)
    if request.method == "POST":
        form = forms.AFARegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Registration will be done shortly")
    form = forms.AFARegistrationForm()
    context = {'form': form, 'ref': reference, 'price': price, 'id': db_user_id, "email": user_email,
               "wallet": 0 if user.wallet is None else user.wallet}
    return render(request, "layouts/services/afa.html", context=context)


def afa_registration_wallet(request):
    if request.method == "POST":
        user = models.CustomUser.objects.get(id=request.user.id)
        phone_number = request.POST.get("phone")
        amount = request.POST.get("amount")
        reference = request.POST.get("reference")
        name = request.POST.get("name")
        card_number = request.POST.get("card")
        occupation = request.POST.get("occupation")
        date_of_birth = request.POST.get("birth")
        price = models.AdminInfo.objects.filter().first().afa_price

        if user.wallet is None:
            return JsonResponse(
                {'status': f'Your wallet balance is low. Contact the admin to recharge.'})
        elif user.wallet <= 0 or user.wallet < float(amount):
            return JsonResponse(
                {'status': f'Your wallet balance is low. Contact the admin to recharge.'})

        new_registration = models.AFARegistration.objects.create(
            user=user,
            reference=reference,
            name=name,
            phone_number=phone_number,
            gh_card_number=card_number,
            occupation=occupation,
            date_of_birth=date_of_birth
        )
        new_registration.save()
        user.wallet -= float(price)
        user.save()
        return JsonResponse({'status': "Your transaction will be completed shortly", 'icon': 'success'})
    return redirect('home')


@login_required(login_url='login')
def big_time(request):
    user = models.CustomUser.objects.get(id=request.user.id)
    status = user.status
    form = forms.BigTimeBundleForm(status)
    reference = helper.ref_generator()
    db_user_id = request.user.id
    user_email = request.user.email

    if request.method == "POST":
        payment_reference = request.POST.get("reference")
        amount_paid = request.POST.get("amount")
        new_payment = models.Payment.objects.create(
            user=request.user,
            reference=payment_reference,
            amount=amount_paid,
            transaction_date=datetime.now(),
            transaction_status="Pending"
        )
        new_payment.save()
        phone_number = request.POST.get("phone")
        offer = request.POST.get("amount")
        if user.status == "User":
            bundle = models.BigTimeBundlePrice.objects.get(price=float(offer)).bundle_volume
        elif user.status == "Agent":
            bundle = models.AgentBigTimeBundlePrice.objects.get(price=float(offer)).bundle_volume
        elif user.status == "Super Agent":
            bundle = models.SuperAgentBigTimeBundlePrice.objects.get(price=float(offer)).bundle_volume
        print(phone_number)
        new_mtn_transaction = models.BigTimeTransaction.objects.create(
            user=request.user,
            bundle_number=phone_number,
            offer=f"{bundle}MB",
            reference=payment_reference,
        )
        new_mtn_transaction.save()
        return JsonResponse({'status': "Your transaction will be completed shortly", 'icon': 'success'})
    user = models.CustomUser.objects.get(id=request.user.id)
    # phone_num = user.phone
    # mtn_dict = {}
    #
    # if user.status == "Agent":
    #     mtn_offer = models.AgentMTNBundlePrice.objects.all()
    # else:
    #     mtn_offer = models.MTNBundlePrice.objects.all()
    # for offer in mtn_offer:
    #     mtn_dict[str(offer)] = offer.bundle_volume
    context = {'form': form,
               "ref": reference, "email": user_email, 'id': db_user_id,
               "wallet": 0 if user.wallet is None else user.wallet}
    return render(request, "layouts/services/big_time.html", context=context)


@login_required(login_url='login')
def history(request):
    user_transactions = models.IShareBundleTransaction.objects.filter(user=request.user).order_by(
        'transaction_date').reverse()
    header = "AirtelTigo Transactions"
    net = "tigo"
    context = {'txns': user_transactions, "header": header, "net": net}
    return render(request, "layouts/history.html", context=context)


@login_required(login_url='login')
def mtn_history(request):
    user_transactions = models.MTNTransaction.objects.filter(user=request.user).order_by('transaction_date').reverse()
    header = "MTN Transactions"
    net = "mtn"
    context = {'txns': user_transactions, "header": header, "net": net}
    return render(request, "layouts/history.html", context=context)


@login_required(login_url='login')
def telecel_history(request):
    user_transactions = models.TelecelTransaction.objects.filter(user=request.user).order_by(
        'transaction_date').reverse()
    header = "Telecel Transactions"
    net = "telecel"
    context = {'txns': user_transactions, "header": header, "net": net}
    return render(request, "layouts/history.html", context=context)


@login_required(login_url='login')
def big_time_history(request):
    user_transactions = models.BigTimeTransaction.objects.filter(user=request.user).order_by(
        'transaction_date').reverse()
    header = "Big Time Transactions"
    net = "bt"
    context = {'txns': user_transactions, "header": header, "net": net}
    return render(request, "layouts/history.html", context=context)


@login_required(login_url='login')
def afa_history(request):
    user_transactions = models.AFARegistration.objects.filter(user=request.user).order_by('transaction_date').reverse()
    header = "AFA Registrations"
    net = "afa"
    context = {'txns': user_transactions, "header": header, "net": net}
    return render(request, "layouts/afa_history.html", context=context)


def verify_transaction(request, reference):
    if request.method == "GET":
        response = helper.verify_paystack_transaction(reference)
        data = response.json()
        try:
            status = data["data"]["status"]
            amount = data["data"]["amount"]
            api_reference = data["data"]["reference"]
            date = data["data"]["paid_at"]
            real_amount = float(amount) / 100
            print(status)
            print(real_amount)
            print(api_reference)
            print(reference)
            print(date)
        except:
            status = data["status"]
        return JsonResponse({'status': status})


@login_required(login_url='login')
def admin_mtn_history(request):
    if request.user.is_staff and request.user.is_superuser:
        all_txns = models.MTNTransaction.objects.all().order_by('-transaction_date')[:1000]
        context = {'txns': all_txns}
        return render(request, "layouts/services/mtn_admin.html", context=context)


@login_required(login_url='login')
def admin_telecel_history(request):
    if request.user.is_staff and request.user.is_superuser:
        all_txns = models.TelecelTransaction.objects.all().order_by('-transaction_date')[:1000]
        context = {'txns': all_txns}
        return render(request, "layouts/services/voda_admin.html", context=context)


@login_required(login_url='login')
def admin_at_history(request):
    if request.user.is_staff and request.user.is_superuser:
        all_txns = models.IShareBundleTransaction.objects.filter().order_by('-transaction_date')[:1000]
        context = {'txns': all_txns}
        return render(request, "layouts/services/at_admin.html", context=context)


@login_required(login_url='login')
def admin_bt_history(request):
    if request.user.is_staff and request.user.is_superuser:
        all_txns = models.BigTimeTransaction.objects.filter().order_by('-transaction_date')[:1000]
        context = {'txns': all_txns}
        return render(request, "layouts/services/bt_admin.html", context=context)


@login_required(login_url='login')
def admin_afa_history(request):
    if request.user.is_staff and request.user.is_superuser:
        all_txns = models.AFARegistration.objects.filter().order_by('-transaction_date')[:1000]
        context = {'txns': all_txns}
        return render(request, "layouts/services/afa_admin.html", context=context)


@login_required(login_url='login')
def mark_as_sent(request, pk, status):
    if request.user.is_staff and request.user.is_superuser:
        txn = models.MTNTransaction.objects.filter(id=pk).first()
        print(txn)
        if status == "Processing":
            txn.transaction_status = "Processing"
            txn.save()
            messages.success(request, f"Transaction Processed")
            return redirect('mtn_admin')
        elif status == "Cancelled":
            txn.transaction_status = "Cancelled"
            txn.save()
            messages.success(request, f"Transaction Cancelled")
            return redirect('mtn_admin')
        elif status == "Refunded":
            txn.transaction_status = "Refunded"
            txn.save()
            messages.success(request, f"Transaction Refunded")
            return redirect('mtn_admin')
        else:
            txn.transaction_status = "Completed"
            txn.save()
            sms_headers = {
                'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
                'Content-Type': 'application/json'
            }

            sms_url = 'https://webapp.usmsgh.com/api/sms/send'
            sms_message = f"{txn.bundle_number} has been credited with {txn.offer}.\nTransaction Reference: {txn.reference}"

            sms_body = {
                'recipient': f"233{txn.user.phone}",
                'sender_id': 'DANWELSTORE',
                'message': sms_message
            }
            response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
            print(response.text)
            return redirect('mtn_admin')


@login_required(login_url='login')
def telecel_mark_as_sent(request, pk, status):
    if request.user.is_staff and request.user.is_superuser:
        txn = models.TelecelTransaction.objects.filter(id=pk).first()
        print(txn)
        if status == "Processing":
            txn.transaction_status = "Processing"
            txn.save()
            messages.success(request, f"Transaction Processed")
            return redirect('telecel_admin')
        elif status == "Cancelled":
            txn.transaction_status = "Cancelled"
            txn.save()
            messages.success(request, f"Transaction Cancelled")
            return redirect('telecel_admin')
        elif status == "Refunded":
            txn.transaction_status = "Refunded"
            txn.save()
            messages.success(request, f"Transaction Refunded")
            return redirect('telecel_admin')
        else:
            txn.transaction_status = "Completed"
            txn.save()
            sms_headers = {
                'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
                'Content-Type': 'application/json'
            }

            sms_url = 'https://webapp.usmsgh.com/api/sms/send'
            sms_message = f"{txn.bundle_number} has been credited with {txn.offer}.\nTransaction Reference: {txn.reference}"

            sms_body = {
                'recipient': f"233{txn.user.phone}",
                'sender_id': 'DANWELSTORE',
                'message': sms_message
            }
            response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
            print(response.text)
            return redirect('telecel_admin')


@login_required(login_url='login')
def at_mark_as_sent(request, pk, status):
    if request.user.is_staff and request.user.is_superuser:
        txn = models.IShareBundleTransaction.objects.filter(id=pk).first()
        print(txn)
        if status == "Processing":
            txn.transaction_status = "Processing"
            txn.save()
            messages.success(request, f"Transaction Processed")
            return redirect('at_admin')
        elif status == "Cancelled":
            txn.transaction_status = "Cancelled"
            txn.save()
            messages.success(request, f"Transaction Cancelled")
            return redirect('at_admin')
        elif status == "Refunded":
            txn.transaction_status = "Refunded"
            txn.save()
            messages.success(request, f"Transaction Refunded")
            return redirect('at_admin')
        else:
            txn.transaction_status = "Completed"
            txn.save()
            sms_headers = {
                'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
                'Content-Type': 'application/json'
            }

            sms_url = 'https://webapp.usmsgh.com/api/sms/send'
            sms_message = f"Your AT transaction has been completed. {txn.bundle_number} has been credited with {txn.offer}.\nTransaction Reference: {txn.reference}"

            sms_body = {
                'recipient': f"233{txn.user.phone}",
                'sender_id': 'DANWELSTORE',
                'message': sms_message
            }
            try:
                response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
                print(response.text)
            except:
                messages.success(request, f"Transaction Completed")
                return redirect('at_admin')
            messages.success(request, f"Transaction Completed")
            return redirect('at_admin')


@login_required(login_url='login')
def bt_mark_as_sent(request, pk, status):
    if request.user.is_staff and request.user.is_superuser:
        txn = models.BigTimeTransaction.objects.filter(id=pk).first()
        print(txn)
        if status == "Processing":
            txn.transaction_status = "Processing"
            txn.save()
            messages.success(request, f"Transaction Processed")
            return redirect('bt_admin')
        elif status == "Cancelled":
            txn.transaction_status = "Cancelled"
            txn.save()
            messages.success(request, f"Transaction Cancelled")
            return redirect('bt_admin')
        elif status == "Refunded":
            txn.transaction_status = "Refunded"
            txn.save()
            messages.success(request, f"Transaction Refunded")
            return redirect('bt_admin')
        else:
            txn.transaction_status = "Completed"
            txn.save()
            sms_headers = {
                'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
                'Content-Type': 'application/json'
            }

            sms_url = 'https://webapp.usmsgh.com/api/sms/send'
            sms_message = f"Your AT BIG TIME transaction has been completed. {txn.bundle_number} has been credited with {txn.offer}.\nTransaction Reference: {txn.reference}"

            sms_body = {
                'recipient': f"233{txn.user.phone}",
                'sender_id': 'DANWELSTORE',
                'message': sms_message
            }
            try:
                response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
                print(response.text)
            except:
                messages.success(request, f"Transaction Completed")
                return redirect('bt_admin')
            messages.success(request, f"Transaction Completed")
            return redirect('bt_admin')


@login_required(login_url='login')
def afa_mark_as_sent(request, pk, status):
    if request.user.is_staff and request.user.is_superuser:
        txn = models.AFARegistration.objects.filter(id=pk).first()
        print(txn)
        if status == "Processing":
            txn.transaction_status = "Processing"
            txn.save()
            messages.success(request, f"Transaction Processed")
            return redirect('afa_admin')
        elif status == "Cancelled":
            txn.transaction_status = "Cancelled"
            txn.save()
            messages.success(request, f"Transaction Cancelled")
            return redirect('afa_admin')
        elif status == "Refunded":
            txn.transaction_status = "Refunded"
            txn.save()
            messages.success(request, f"Transaction Refunded")
            return redirect('afa_admin')
        elif status == "Under Verification":
            txn.transaction_status = "Under Verification"
            txn.save()
            messages.success(request, f"Transaction Under Verification")
            return redirect('afa_admin')
        else:
            txn.transaction_status = "Completed"
            txn.save()
            sms_headers = {
                'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
                'Content-Type': 'application/json'
            }

            sms_url = 'https://webapp.usmsgh.com/api/sms/send'
            sms_message = f"Your AFA Registration has been completed. {txn.phone_number} has been registered.\nTransaction Reference: {txn.reference}"

            sms_body = {
                'recipient': f"233{txn.user.phone}",
                'sender_id': 'DANWELSTORE',
                'message': sms_message
            }
            response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
            print(response.text)
            messages.success(request, f"Transaction Completed")
            return redirect('afa_admin')


def credit_user(request):
    form = forms.CreditUserForm()
    if request.user.is_superuser:
        if request.method == "POST":
            form = forms.CreditUserForm(request.POST)
            if form.is_valid():
                user = form.cleaned_data["user"]
                amount = form.cleaned_data["amount"]
                print(user)
                print(amount)
                user_needed = models.CustomUser.objects.get(username=user)
                if user_needed.wallet is None:
                    user_needed.wallet = float(amount)
                else:
                    user_needed.wallet += float(amount)
                user_needed.save()
                print(user_needed.username)
                messages.success(request, "Crediting Successful")
                sms_headers = {
                    'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
                    'Content-Type': 'application/json'
                }

                sms_url = 'https://webapp.usmsgh.com/api/sms/send'
                sms_message = f"Hello {user_needed},\nYour DataForAll wallet has been credit with GHS{amount}.\nDataForAll."

                sms_body = {
                    'recipient': f"233{user_needed.phone}",
                    'sender_id': 'DANWELSTORE',
                    'message': sms_message
                }
                response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
                print(response.text)
                return redirect('credit_user')
        context = {'form': form}
        return render(request, "layouts/services/credit.html", context=context)
    else:
        messages.error(request, "Access Denied")
        return redirect('home')


@login_required(login_url='login')
def topup_info(request):
    if request.method == "POST":
        admin = models.AdminInfo.objects.filter().first().phone_number
        user = models.CustomUser.objects.get(id=request.user.id)
        amount = request.POST.get("amount")
        print(amount)
        reference = helper.top_up_ref_generator()
        new_topup_request = models.TopUpRequest.objects.create(
            user=request.user,
            amount=amount,
            reference=reference,
        )
        new_topup_request.save()

        sms_headers = {
            'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
            'Content-Type': 'application/json'
        }

        sms_url = 'https://webapp.usmsgh.com/api/sms/send'
        sms_message = f"A top up request has been placed.\nGHS{amount} for {user}.\nReference: {reference}"

        sms_body = {
            'recipient': f"233{admin}",
            'sender_id': 'DANWELSTORE',
            'message': sms_message
        }

        # response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
        # print(response.text)

        messages.success(request,
                         f"Your Request has been sent successfully. Kindly go on to pay to {admin} and use the reference stated as reference. Reference: {reference}")
        return redirect("request_successful", reference)
    return render(request, "layouts/topup-info.html")


@login_required(login_url='login')
def request_successful(request, reference):
    admin = models.AdminInfo.objects.filter().first()
    context = {
        "name": admin.name,
        "number": f"0{admin.momo_number}",
        "channel": admin.payment_channel,
        "reference": reference
    }
    return render(request, "layouts/services/request_successful.html", context=context)


def topup_list(request):
    if request.user.is_superuser:
        topup_requests = models.TopUpRequest.objects.all().order_by('date').reverse()
        context = {
            'requests': topup_requests,
        }
        return render(request, "layouts/services/topup_list.html", context=context)
    else:
        messages.error(request, "Access Denied")
        return redirect('home')


@login_required(login_url='login')
def credit_user_from_list(request, reference):
    if request.user.is_superuser:
        crediting = models.TopUpRequest.objects.filter(reference=reference).first()
        user = crediting.user
        custom_user = models.CustomUser.objects.get(username=user.username)
        if crediting.status:
            return redirect('topup_list')
        amount = crediting.amount
        print(user)
        print(user.phone)
        print(amount)
        custom_user.wallet += amount
        custom_user.save()
        crediting.status = True
        crediting.credited_at = datetime.now()
        crediting.save()
        sms_headers = {
            'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
            'Content-Type': 'application/json'
        }

        sms_url = 'https://webapp.usmsgh.com/api/sms/send'
        sms_message = f"Hello,\nYour wallet has been topped up with GHS{amount}.\nReference: {reference}.\nThank you"

        sms_body = {
            'recipient': f"233{custom_user.phone}",
            'sender_id': 'DANWELSTORE',
            'message': sms_message
        }
        try:
            response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
            print(response.text)
        except:
            pass
        messages.success(request, f"{user} has been credited with {amount}")
        return redirect('topup_list')


def populate_custom_users_from_excel(request):
    # Read the Excel file using pandas
    if request.method == 'POST':
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            excel_file = request.FILES['file']

            # Process the uploaded Excel file
            df = pd.read_excel(excel_file)
            counter = 0
            # Iterate through rows to create CustomUser instances
            for index, row in df.iterrows():
                print(counter)
                # Create a CustomUser instance for each row
                custom_user = CustomUser.objects.create(
                    first_name=row['first_name'],
                    last_name=row['last_name'],
                    username=str(row['username']),
                    email=row['email'],
                    phone=row['phone'],
                    wallet=float(row['wallet']),
                    status=str(row['status']),
                    password1=row['password1'],
                    password2=row['password2'],
                    is_superuser=row['is_superuser'],
                    is_staff=row['is_staff'],
                    is_active=row['is_active'],
                    password=row['password']
                )

                custom_user.save()

                # group_names = row['groups'].split(',')  # Assuming groups are comma-separated
                # groups = Group.objects.filter(name__in=group_names)
                # custom_user.groups.set(groups)
                #
                # if row['user_permissions']:
                #     permission_ids = [int(pid) for pid in row['user_permissions'].split(',')]
                #     permissions = Permission.objects.filter(id__in=permission_ids)
                #     custom_user.user_permissions.set(permissions)
                print("killed")
                counter = counter + 1
            messages.success(request, 'All done')
    else:
        form = UploadFileForm()
    return render(request, 'layouts/import_users.html', {'form': form})


def delete_custom_users(request):
    CustomUser.objects.all().delete()
    return HttpResponseRedirect('Done')


@csrf_exempt
def hubtel_webhook(request):
    if request.method == 'POST':
        print("hit the webhook")
        try:
            payload = request.body.decode('utf-8')
            print("Hubtel payment Info: ", payload)
            json_payload = json.loads(payload)
            print(json_payload)

            data = json_payload.get('Data')
            print(data)
            reference = data.get('ClientReference')
            print(reference)
            txn_status = data.get('Status')
            txn_description = data.get('Description')
            amount = data.get('Amount')
            print(txn_status, amount)

            if txn_status == 'Success':
                print("success")
                transaction_saved = models.Payment.objects.get(reference=reference, transaction_status="Unfinished")
                transaction_saved.transaction_status = "Paid"
                transaction_saved.payment_description = txn_description
                transaction_saved.amount = amount
                transaction_saved.save()
                transaction_details = "hi"
                transaction_channel = "topup"
                user = transaction_saved.user
                # receiver = collection_saved['number']
                # bundle_volume = collection_saved['data_volume']
                # name = collection_saved['name']
                # email = collection_saved['email']
                # phone_number = collection_saved['buyer']
                # date_and_time = collection_saved['date_and_time']
                # txn_type = collection_saved['type']
                # user_id = collection_saved['uid']
                print(transaction_details, transaction_channel)

                if transaction_channel == "ishare":
                    # offer = transaction_details["offers"]
                    # phone_number = transaction_details["phone_number"]
                    #
                    # if user.status == "User":
                    #     bundle = models.IshareBundlePrice.objects.get(price=float(offer)).bundle_volume
                    # elif user.status == "Agent":
                    #     bundle = models.AgentIshareBundlePrice.objects.get(price=float(offer)).bundle_volume
                    # elif user.status == "Super Agent":
                    #     bundle = models.SuperAgentIshareBundlePrice.objects.get(price=float(offer)).bundle_volume
                    # else:
                    #     bundle = models.IshareBundlePrice.objects.get(price=float(offer)).bundle_volume
                    # new_transaction = models.IShareBundleTransaction.objects.create(
                    #     user=user,
                    #     bundle_number=phone_number,
                    #     offer=f"{bundle}MB",
                    #     reference=reference,
                    #     transaction_status="Pending"
                    # )
                    # print("created")
                    # new_transaction.save()
                    #
                    # print("===========================")
                    # print(phone_number)
                    # print(bundle)
                    # print(user)
                    # print(reference)
                    # send_bundle_response = helper.send_bundle(user, phone_number, bundle, reference)
                    # data = send_bundle_response.json()
                    #
                    # print(data)
                    #
                    # sms_headers = {
                    #     'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
                    #     'Content-Type': 'application/json'
                    # }
                    #
                    # sms_url = 'https://webapp.usmsgh.com/api/sms/send'
                    #
                    # if send_bundle_response.status_code == 200:
                    #     if data["code"] == "0000":
                    #         transaction_to_be_updated = models.IShareBundleTransaction.objects.get(
                    #             reference=reference)
                    #         print("got here")
                    #         print(transaction_to_be_updated.transaction_status)
                    #         transaction_to_be_updated.transaction_status = "Completed"
                    #         transaction_to_be_updated.save()
                    #         print(user.phone)
                    #         print("***********")
                    #         receiver_message = f"Your bundle purchase has been completed successfully. {bundle}MB has been credited to you by {user.phone}.\nReference: {reference}\n"
                    #         sms_message = f"Hello @{user.username}. Your bundle purchase has been completed successfully. {bundle}MB has been credited to {phone_number}.\nReference: {reference}\nThank you for using Data4All GH.\n\nThe Data4All GH"
                    #
                    #         sms_body = {
                    #             'recipient': f"233{user.phone}",
                    #             'sender_id': 'DANWELSTORE',
                    #             'message': sms_message
                    #         }
                    #         try:
                    #             response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
                    #             print(response.text)
                    #         except:
                    #             print("message not sent")
                    #             pass
                    #         return JsonResponse({'status': 'Transaction Completed Successfully'}, status=200)
                    #     else:
                    #         transaction_to_be_updated = models.IShareBundleTransaction.objects.get(
                    #             reference=reference)
                    #         transaction_to_be_updated.transaction_status = "Failed"
                    #         new_transaction.save()
                    #         sms_message = f"Hello @{user.username}. Something went wrong with your transaction. Contact us for enquiries.\nBundle: {bundle}MB\nPhone Number: {phone_number}.\nReference: {reference}\nThank you for using Data4All GH.\n\nThe Data4All GH"
                    #
                    #         sms_body = {
                    #             'recipient': f"233{user.phone}",
                    #             'sender_id': 'Data4All',
                    #             'message': sms_message
                    #         }
                    #         return JsonResponse({'status': 'Something went wrong'}, status=500)
                    # else:
                    #     transaction_to_be_updated = models.IShareBundleTransaction.objects.get(
                    #         reference=reference)
                    #     transaction_to_be_updated.transaction_status = "Failed"
                    #     new_transaction.save()
                    #     sms_message = f"Hello @{user.username}. Something went wrong with your transaction. Contact us for enquiries.\nBundle: {bundle}MB\nPhone Number: {phone_number}.\nReference: {payment_reference}\nThank you for using Data4All GH.\n\nThe Data4All GH"
                    #
                    #     sms_body = {
                    #         'recipient': f'233{user.phone}',
                    #         'sender_id': 'Data4All',
                    #         'message': sms_message
                    #     }
                    #
                    #     # response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
                    #     #
                    #     # print(response.text)
                    #     return JsonResponse({'status': 'Something went wrong', 'icon': 'error'})
                    ...
                elif transaction_channel == "mtn":
                    # offer = transaction_details["offers"]
                    # phone_number = transaction_details["phone_number"]
                    #
                    # if user.status == "User":
                    #     bundle = models.MTNBundlePrice.objects.get(price=float(offer)).bundle_volume
                    # elif user.status == "Agent":
                    #     bundle = models.AgentMTNBundlePrice.objects.get(price=float(offer)).bundle_volume
                    # elif user.status == "Super Agent":
                    #     bundle = models.SuperAgentMTNBundlePrice.objects.get(price=float(offer)).bundle_volume
                    # else:
                    #     bundle = models.MTNBundlePrice.objects.get(price=float(offer)).bundle_volume
                    #
                    # print(phone_number)
                    # new_mtn_transaction = models.MTNTransaction.objects.create(
                    #     user=user,
                    #     bundle_number=phone_number,
                    #     offer=f"{bundle}MB",
                    #     reference=reference,
                    # )
                    # new_mtn_transaction.save()
                    # return JsonResponse({'status': "Your transaction will be completed shortly"}, status=200)
                    ...
                elif transaction_channel == "bigtime":
                    # offer = transaction_details["offers"]
                    # phone_number = transaction_details["phone_number"]
                    # if user.status == "User":
                    #     bundle = models.BigTimeBundlePrice.objects.get(price=float(offer)).bundle_volume
                    # elif user.status == "Agent":
                    #     bundle = models.AgentBigTimeBundlePrice.objects.get(price=float(offer)).bundle_volume
                    # elif user.status == "Super Agent":
                    #     bundle = models.SuperAgentBigTimeBundlePrice.objects.get(price=float(offer)).bundle_volume
                    # else:
                    #     bundle = models.SuperAgentBigTimeBundlePrice.objects.get(price=float(offer)).bundle_volume
                    # print(phone_number)
                    # new_mtn_transaction = models.BigTimeTransaction.objects.create(
                    #     user=user,
                    #     bundle_number=phone_number,
                    #     offer=f"{bundle}MB",
                    #     reference=reference,
                    # )
                    # new_mtn_transaction.save()
                    # return JsonResponse({'status': "Your transaction will be completed shortly"}, status=200)
                    ...
                elif transaction_channel == "afa":
                    # name = transaction_details["name"]
                    # phone_number = transaction_details["phone"]
                    # gh_card_number = transaction_details["card"]
                    # occupation = transaction_details["occupation"]
                    # date_of_birth = transaction_details["date_of_birth"]
                    #
                    # new_afa_reg = models.AFARegistration.objects.create(
                    #     user=user,
                    #     phone_number=phone_number,
                    #     gh_card_number=gh_card_number,
                    #     name=name,
                    #     occupation=occupation,
                    #     reference=reference,
                    #     date_of_birth=date_of_birth
                    # )
                    # new_afa_reg.save()
                    # return JsonResponse({'status': "Your transaction will be completed shortly"}, status=200)
                    ...
                elif transaction_channel == "topup":
                    amount = amount

                    user.wallet += float(amount)
                    user.save()

                    new_topup = models.TopUpRequest.objects.create(
                        user=user,
                        reference=reference,
                        amount=amount,
                        status=True,
                    )
                    new_topup.save()
                    response1 = requests.get(
                        f"https://sms.arkesel.com/sms/api?action=send-sms&api_key=OnBuSjBXc1pqN0xrQXIxU1A=&to=0{user.phone}&from=DANWELSTORE&sms=Your Bestplug wallet has been credited with {amount}. Thank You.")
                    print(response1.text)
                    return JsonResponse({'status': "Wallet Credited"}, status=200)
                else:
                    print("no type found")
                    return JsonResponse({'message': "No Type Found"}, status=500)
            else:
                print("Transaction was not Successful")
                return JsonResponse({'message': 'Transaction Failed'}, status=200)
        except Exception as e:
            print("Error Processing hubtel webhook:", str(e))
            return JsonResponse({'status': 'error'}, status=500)
    else:
        print("not post")
        return JsonResponse({'message': 'Not Found'}, status=404)


from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator

def password_reset_request(request):
    if request.method == "POST":
        password_reset_form = PasswordResetForm(request.POST)
        if password_reset_form.is_valid():
            data = password_reset_form.cleaned_data['email']
            user = models.CustomUser.objects.filter(email=data).first()
            current_user = user
            if user:
                subject = "Password Reset Requested"
                email_template_name = "password/password_reset_message.txt"
                c = {
                    "name": user.first_name,
                    "email": user.email,
                    'domain': 'www.danwelstoregh.com',
                    'site_name': 'DanWel Store GH',
                    "uid": urlsafe_base64_encode(force_bytes(user.pk)),
                    "user": user,
                    'token': default_token_generator.make_token(user),
                    'protocol': 'https',
                }
                email = render_to_string(email_template_name, c)

                sms_headers = {
                    'Authorization': 'Bearer 1320|DMvAzhkgqCGgsuDs6DHcTKnt8xcrFnD48HEiRbvr',
                    'Content-Type': 'application/json'
                }

                sms_url = 'https://webapp.usmsgh.com/api/sms/send'

                sms_body = {
                    'recipient': f"233{user.phone}",
                    'sender_id': 'DANWELSTORE',
                    'message': email
                }
                response = requests.request('POST', url=sms_url, params=sms_body, headers=sms_headers)
                print(response.text)
                # requests.get(
                #     f"https://sms.arkesel.com/sms/api?action=send-sms&api_key=UnBzemdvanJyUGxhTlJzaVVQaHk&to=0{current_user.phone}&from=GEO_AT&sms={email}")

                return redirect("/password_reset/done/")
    password_reset_form = PasswordResetForm()
    return render(request=request, template_name="password/password_reset.html",
                  context={"password_reset_form": password_reset_form})
