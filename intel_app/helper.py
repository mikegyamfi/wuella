import secrets
import json
import requests
from datetime import datetime
from decouple import config

from intel_app.models import MTNTransaction

ishare_map = {
    2: 50,
    4: 52,
    7: 2000,
    10: 3000,
    12: 4000,
    15: 5000,
    18: 6000,
    22: 7000,
    25: 8000,
    30: 10000,
    45: 15000,
    60: 20000,
    75: 25000,
    90: 30000,
    120: 40000,
    145: 50000,
    285: 100000,
    560: 200000
}


def ref_generator():
    now_time = datetime.now().strftime('%H%M%S')
    secret = secrets.token_hex(10)

    return f"{now_time}{secret}".upper()




import random
import string
import time
import hashlib


def mtn_ref_generator(length=20):
    """
    Generates a unique reference of the format:
    'X_MTN{<HASHED_PART>}_RAY'

    Uses current time + random characters + SHA-256 hashing to
    reduce collisions. Checks the database to ensure the reference
    doesn't already exist.
    """
    if length < 15:
        raise ValueError("Length must be at least 15 characters.")

    while True:
        # Current time in nanoseconds to ensure (near) uniqueness
        timestamp = str(int(time.time() * 1e9))

        # Random characters
        characters = string.ascii_uppercase + string.digits
        random_part = ''.join(random.choices(characters, k=length - 5))

        # Combine timestamp and random part
        base_ref = timestamp + random_part

        # Hash the base reference for additional uniqueness
        hashed_ref = hashlib.sha256(base_ref.encode()).hexdigest()
        # Take the first `length` characters and uppercase
        core_reference = hashed_ref[:length].upper()

        # Final format
        new_ref = f"DAN_MTN{core_reference}WEL"

        # Check if this reference already exists in the database
        if not MTNTransaction.objects.filter(reference=new_ref).exists():
            return new_ref


def top_up_ref_generator():
    now_time = datetime.now().strftime('%H%M')
    secret = secrets.token_hex(7)

    return f"TOPUP-{now_time}{secret}".upper()


def send_bundle(user, receiver, bundle_amount, reference):
    url = "https://console.bestpaygh.com/api/flexi/v1/new_transaction/"

    headers = {
        "api-key": config("API_KEY"),
        "api-secret": config("API_SECRET"),
        'Content-Type': 'application/json'
    }

    print("====================================")
    print(user.phone)
    print(user.first_name)
    print(user.last_name)
    print(user.email)
    print(receiver)
    print(reference)
    print(bundle_amount)
    print("=====================================")

    payload = json.dumps({
        "first_name": user.first_name,
        "last_name": user.last_name,
        "account_number": f"0{user.phone}",
        "receiver": receiver,
        "account_email": user.email,
        "reference": reference,
        "bundle_amount": bundle_amount
    })

    response = requests.request("POST", url, headers=headers, data=payload)

    print(response.json)
    return response

    # url = "https://console.bestpaygh.com/api/flexi/v1/new_transaction/"
    #
    # headers = {
    # #     "api-key": config("API_KEY"),
    #     "api-secret": config("API_SECRET"),
    #     'Content-Type': 'application/json'
    # }
    #
    # print("====================================")
    # print(user.phone)
    # print(user.first_name)
    # print(user.last_name)
    # print(user.email)
    # print(receiver)
    # print(reference)
    # print(bundle_amount)
    # print("=====================================")
    #
    # payload = json.dumps({
    #     "first_name": user.first_name,
    #     "last_name": user.last_name,
    #     "account_number": f"0{user.phone}",
    #     "receiver": receiver,
    #     "account_email": user.email,
    #     "reference": reference,
    #     "bundle_amount": bundle_amount
    # })
    #
    # response = requests.request("POST", url, headers=headers, data=payload)
    #
    # print(response.json)
    # return response


def controller_send_bundle(receiver, bundle_amount, reference):
    url = "https://www.geosams.com/controller/api/send_bundle/"

    payload = json.dumps({
        "phone_number": str(receiver),
        "amount": int(bundle_amount),
        "reference": str(reference),
        "network": "AT"
    })
    headers = {
        'Authorization': config("CONTROLLER_TOKEN"),
        'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, data=payload)
    print(response.text)
    return response


def value_4_moni_send_bundle(receiver, bundle_amount, reference):
    url = "https://www.value4moni.com/api/v1/inititate_transaction"

    # Payload data to send in the request
    data = {
        "API_Key": config("VALUE_API_KEY"),
        "Receiver": str(receiver),
        "Volume": str(bundle_amount),
        "Reference": str(reference),
        "Package_Type": "AirtelTigo"
    }

    # Make the POST request
    response = requests.post(url, json=data)

    # Print the response from the server
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")

    return response


def verify_paystack_transaction(reference):
    url = f"https://api.paystack.co/transaction/verify/{reference}"

    headers = {
        "Authorization": "Bearer sk_test_d8585b8c1c61a364640e9acbb3bc8046f5fb9acd"
    }

    response = requests.request("GET", url, headers=headers)

    print(response.json())

    return response

