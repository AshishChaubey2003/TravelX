# Kafka topic names. Always import these constants; never hardcode a topic
# name at a call site, so a rename never leaves a producer/consumer stranded.
TOPIC_BOOKING_CREATED = 'booking.created'
TOPIC_PAYMENT_SUCCESS = 'payment.success'
TOPIC_PAYMENT_FAILED = 'payment.failed'
TOPIC_BOOKING_CANCELLED = 'booking.cancelled'