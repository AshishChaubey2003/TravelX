from apps.kafka_events.producers import publish_payment_success, publish_payment_failed

# Payment success mein:
publish_payment_success(booking, payment)

# Payment failed mein:
publish_payment_failed(booking)