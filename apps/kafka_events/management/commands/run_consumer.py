from django.core.management.base import BaseCommand
from apps.kafka_events.consumers import run_booking_consumer


class Command(BaseCommand):
    help = 'Start Kafka consumer'

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('Starting Kafka consumer...')
        )
        run_booking_consumer()