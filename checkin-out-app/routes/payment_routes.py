import os
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, User, Subscription, Transaction
from ..utils import sanitize_input, get_current_time, get_mpesa_access_token, validate_mpesa_signature
import stripe
import paypalrestsdk
import uuid
import base64

payment_bp = Blueprint('payment', __name__, url_prefix='/payment')

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
paypal_mode = 'live' if os.getenv('FLASK_ENV') == 'production' else 'sandbox'
paypalrestsdk.configure({
    "mode": paypal_mode,
    "client_id": os.getenv('PAYPAL_CLIENT_ID'),
    "client_secret": os.getenv('PAYPAL_CLIENT_SECRET')
})

@payment_bp.route('/subscribe', methods=['GET', 'POST'])
@jwt_required()
def subscribe():
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user:
            flash('User not found.', 'danger')
            return render_template('error.html', message='User not found', config=app.config, hasLoggedIn=False, username='', userRole='', current_year=datetime.now().year, datetime=datetime)
        if request.method == 'GET':
            subscription = session.query(Subscription).filter_by(organization_id=username).first()
            if not subscription:
                org_type = user.organization_type
                default_plan = app.config['ORGANIZATION_TYPES'].get(org_type, {}).get('default_plan', 'free')
                employee_limit = app.config['SUBSCRIPTION_TIERS'][default_plan]['employee_limit']
                subscription = Subscription(organization_id=username, plan=default_plan, employee_limit=employee_limit, start_date=date.today().isoformat())
                session.add(subscription)
                session.commit()
            transaction_id = str(uuid.uuid4())
            return render_template(
                'subscribe.html',
                config=app.config,
                subscription=subscription._asdict(),
                subscription_tiers=app.config['SUBSCRIPTION_TIERS'],
                stripe_publishable_key=app.config['STRIPE_PUBLISHABLE_KEY'],
                paypal_client_id=os.getenv('PAYPAL_CLIENT_ID'),
                transaction_id=transaction_id,
                hasLoggedIn=True,
                username=username,
                userRole='admin',
                current_year=datetime.now().year,
                datetime=datetime
            )
        plan_type = request.form.get('plan_type')
        payment_method = request.form.get('payment_method')
        transaction_id = request.form.get('transaction_id')
        if not all([plan_type, payment_method, transaction_id]):
            return jsonify({'error': 'Required fields missing'}), 400
        if plan_type not in app.config['SUBSCRIPTION_TIERS']:
            return jsonify({'error': 'Invalid plan type'}), 400
        amount = app.config['SUBSCRIPTION_TIERS'][plan_type]['price']
        employee_limit = app.config['SUBSCRIPTION_TIERS'][plan_type]['employee_limit']
        new_transaction = Transaction(transaction_id=transaction_id, username=username, amount=amount, plan=plan_type, payment_method=payment_method, status='pending', created_at=get_current_time().strftime('%Y-%m-%d %H:%M:%S'))
        session.add(new_transaction)
        session.commit()
        if amount == 0:
            subscription.plan = plan_type
            subscription.employee_limit = employee_limit
            subscription.start_date = date.today().isoformat()
            new_transaction.status = 'completed'
            session.commit()
            flash('Subscribed to free plan.', 'success')
            return render_template('success.html', message=f'Subscription upgraded to {plan_type} plan', config=app.config, hasLoggedIn=True, username=username, userRole='admin', current_year=datetime.now().year, datetime=datetime)
        if payment_method == 'stripe':
            payment_method_id = request.form.get('payment_method_id')
            if not payment_method_id:
                return jsonify({'error': 'Card details required'}), 400
            intent = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'unit_amount': int(amount * 100),
                        'product_data': {'name': f'{plan_type.capitalize()} Subscription'},
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=f"{request.host_url}completed/success?transaction_id={transaction_id}&plan={plan_type}",
                cancel_url=f"{request.host_url}completed/canceled?error=Payment%20canceled",
                metadata={'username': username, 'transaction_id': transaction_id}
            )
            return jsonify({'success': True, 'session_id': intent.id})
        elif payment_method == 'paypal':
            paypal_order_id = request.form.get('paypal_order_id')
            if not paypal_order_id:
                return jsonify({'error': 'PayPal order ID required'}), 400
            payment = paypalrestsdk.Order.find(paypal_order_id)
            if payment.capture():
                subscription.plan = plan_type
                subscription.employee_limit = employee_limit
                subscription.start_date = date.today().isoformat()
                subscription.end_date = (get_current_time() + timedelta(days=app.config['SUBSCRIPTION_DURATION_DAYS'])).strftime('%Y-%m-%d')
                new_transaction.status = 'completed'
                session.commit()
                return jsonify({'success': True, 'order_id': paypal_order_id, 'plan': plan_type})
            return jsonify({'error': 'PayPal payment failed'}), 400
        elif payment_method == 'mpesa':
            mpesa_number = request.form.get('mpesa_number')
            if not mpesa_number or not re.match(r'^2547\d{8}$', mpesa_number):
                return jsonify({'error': 'Valid M-Pesa phone number required'}), 400
            access_token = get_mpesa_access_token()
            if not access_token:
                return jsonify({'error': 'M-Pesa access token error'}), 500
            timestamp = get_current_time().strftime('%Y%m%d%H%M%S')
            password = base64.b64encode(f"{app.config['MPESA_SHORTCODE']}{app.config['MPESA_PASSKEY']}{timestamp}".encode()).decode()
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            payload = {
                "BusinessShortCode": app.config['MPESA_SHORTCODE'],
                "Password": password,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": amount,
                "PartyA": mpesa_number,
                "PartyB": app.config['MPESA_SHORTCODE'],
                "PhoneNumber": mpesa_number,
                "CallBackURL": f"{request.host_url}mpesa/callback",
                "AccountReference": f"Sub-{username}-{plan_type}-{transaction_id}",
                "TransactionDesc": f"Subscription to {plan_type} plan"
            }
            response = requests.post("https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest" if os.getenv('FLASK_ENV') != 'production' else "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest", json=payload, headers=headers, timeout=30)
            result = response.json()
            if response.status_code == 200 and result.get('ResponseCode') == '0':
                return jsonify({'success': True, 'message': 'M-Pesa payment request sent'})
            return jsonify({'error': 'M-Pesa payment failed'}), 400
        return jsonify({'error': 'Invalid payment method'}), 400

@payment_bp.route('/mpesa/callback', methods=['POST'])
def mpesa_callback():
    data = request.get_json()
    if not validate_mpesa_signature(data):
        return jsonify({'error': 'Invalid signature'}), 400
    if data['Body']['stkCallback']['ResultCode'] == 0:
        callback_data = data['Body']['stkCallback']['CallbackMetadata']['Item']
        account_reference = next(item['Value'] for item in callback_data if item['Name'] == 'AccountReference')
        with db.session as session:
            if account_reference.startswith('Sub-'):
                _, username, plan, transaction_id = account_reference.split('-')
                transaction = session.query(Transaction).filter_by(transaction_id=transaction_id, status='pending').first()
                if transaction:
                    transaction.status = 'completed'
                    subscription = session.query(Subscription).filter_by(organization_id=username).first()
                    subscription.plan = plan
                    subscription.employee_limit = app.config['SUBSCRIPTION_TIERS'][plan]['employee_limit']
                    subscription.start_date = date.today().isoformat()
                    subscription.end_date = (get_current_time() + timedelta(days=app.config['SUBSCRIPTION_DURATION_DAYS'])).strftime('%Y-%m-%d')
                    session.commit()
                    return jsonify({'success': True, 'message': 'M-Pesa payment processed'})
            elif account_reference.startswith('Booking-'):
                guest_id = account_reference.split('-')[1]
                booking = session.query(Booking).filter_by(guest_id=guest_id).first()
                if booking:
                    booking.payment_status = 'completed'
                    session.commit()
                    return jsonify({'success': True, 'message': 'M-Pesa payment for booking processed'})
    return jsonify({'error': 'M-Pesa payment failed'}), 400

@payment_bp.route('/success')
@jwt_required()
def payment_success():
    username = sanitize_input(get_jwt_identity())
    transaction_id = sanitize_input(request.args.get('transaction_id'))
    plan = sanitize_input(request.args.get('plan'))
    with db.session as session:
        transaction = session.query(Transaction).filter_by(transaction_id=transaction_id).first()
        if not transaction or transaction.status == 'completed':
            flash('Invalid or already processed transaction.', 'danger')
            return render_template('error.html', message='Invalid or already processed transaction.', config=app.config, hasLoggedIn=True, username=username, userRole='admin', current_year=datetime.now().year, datetime=datetime)
        transaction.status = 'completed'
        subscription = session.query(Subscription).filter_by(organization_id=username).first()
        subscription.plan = plan
        subscription.employee_limit = app.config['SUBSCRIPTION_TIERS'][plan]['employee_limit']
        subscription.start_date = date.today().isoformat()
        subscription.end_date = (get_current_time() + timedelta(days=app.config['SUBSCRIPTION_DURATION_DAYS'])).strftime('%Y-%m-%d')
        session.commit()
        flash(f'Subscription upgraded to {plan} successfully.', 'success')
    return render_template('success.html', message=f'Subscription upgraded to {plan} successfully.', config=app.config, hasLoggedIn=True, username=username, userRole='admin', current_year=datetime.now().year, datetime=datetime)

@payment_bp.route('/cancel')
@jwt_required()
def payment_cancel():
    flash('Payment cancelled.', 'info')
    return render_template('error.html', message='Payment was canceled.', config=app.config, hasLoggedIn=True, username=get_jwt_identity(), userRole='admin', current_year=datetime.now().year, datetime=datetime)