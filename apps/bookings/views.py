from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.db import IntegrityError, transaction
from .models import Booking
from .serializers import BookingSerializer, BookingCreateSerializer
from .services import BookingService
from .idempotency import REPLAY_HEADER, booking_fingerprint, read_idempotency_key

# Still needed by BookingCreateView to disambiguate 404 on resource not found.
from apps.hotels.models import Hotel
from apps.adventures.models import Adventure
from apps.vehicles.models import Vehicle
from apps.core.flow_health import record_flow


class BookingCreateView(APIView):
    """
    Create a booking.

    Optional `Idempotency-Key: <UUID>` header. With it, a retried request
    returns the original booking (200 + Idempotent-Replay: true) instead of
    creating a second one, and reusing the key with a different payload is a
    409. Without it, behaviour is exactly as before: a server-generated key
    and no deduplication.

    The UNIQUE constraint on Booking.idempotency_key - not the pre-check
    below - is what makes this safe under concurrency.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        key, key_error = read_idempotency_key(request)
        if key_error:
            record_flow('booking_create', 'rejected', reason='invalid_idempotency_key')
            return Response({'error': key_error}, status=status.HTTP_400_BAD_REQUEST)

        serializer = BookingCreateSerializer(data=request.data)
        if not serializer.is_valid():
            record_flow('booking_create', 'rejected', reason='invalid_input')
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        fingerprint = booking_fingerprint(serializer.validated_data) if key else None

        if key:
            decided = self._replay_or_conflict(request.user, key, fingerprint)
            if decided is not None:
                return decided

        try:
            booking = BookingService.create_booking(
                user=request.user,
                data=serializer.validated_data,
                idempotency_key=key,
                idempotency_fingerprint=fingerprint,
            )
        except IntegrityError:
            # Lost a concurrent race on the unique idempotency_key. By now
            # create_booking's @transaction.atomic has rolled back and exited,
            # so this query runs on a clean connection, not inside a broken
            # transaction.
            if key:
                decided = self._replay_or_conflict(request.user, key, fingerprint)
                if decided is not None:
                    return decided
            record_flow('booking_create', 'failure', reason='IntegrityError', exc_info=True)
            raise
        except ValueError as e:
            # Either a genuine business-rule violation, or we lost a race and
            # the winner took the last of the inventory. Check for a winner
            # before reporting a rule violation, or an honest retry would be
            # told "sold out" for a booking that actually exists.
            if key:
                decided = self._replay_or_conflict(request.user, key, fingerprint)
                if decided is not None:
                    return decided
            record_flow('booking_create', 'rejected', reason='rule_violation')
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except (Hotel.DoesNotExist, Adventure.DoesNotExist, Vehicle.DoesNotExist):
            record_flow('booking_create', 'rejected', reason='resource_not_found')
            return Response(
                {'error': 'One or more requested resources (hotel, adventure, or vehicle) were not found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception:
            # Same behaviour as before (the exception still propagates);
            # we only make it visible in the flow metrics/logs first.
            record_flow('booking_create', 'failure', reason='unexpected', exc_info=True)
            raise

        response = Response(
            BookingSerializer(booking).data,
            status=status.HTTP_201_CREATED
        )
        record_flow('booking_create', 'success', booking_id=booking.id)
        return response

    def _replay_or_conflict(self, user, key, fingerprint):
        """
        None -> no booking holds this key; the caller proceeds to create.
        200  -> same key, same user, same fingerprint: replay the original.
        409  -> the key is taken by a different payload, or another user.

        The lookup is deliberately not filtered by user: the unique constraint
        is global, so a key held by someone else must be detected as a
        conflict rather than missed and retried into an IntegrityError - and
        another user's booking must never be replayed back to this caller.
        """
        existing = Booking.objects.filter(idempotency_key=key).first()
        if existing is None:
            return None

        if existing.user_id != user.id:
            record_flow('booking_create', 'rejected', reason='idempotency_key_conflict')
            return Response(
                {'error': 'This Idempotency-Key has already been used.'},
                status=status.HTTP_409_CONFLICT,
            )

        if existing.idempotency_fingerprint != fingerprint:
            record_flow('booking_create', 'rejected', reason='idempotency_payload_mismatch')
            return Response(
                {'error': 'This Idempotency-Key was used with a different request payload.'},
                status=status.HTTP_409_CONFLICT,
            )

        response = Response(
            BookingSerializer(existing).data,
            status=status.HTTP_200_OK,
        )
        response[REPLAY_HEADER] = 'true'
        record_flow(
            'booking_create', 'success',
            booking_id=existing.id, reason='idempotent_replay',
        )
        return response


class BookingListView(generics.ListAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Booking.objects.filter(
            user=self.request.user
        ).prefetch_related('items')


class BookingDetailView(generics.RetrieveAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Booking.objects.filter(user=self.request.user)


class BookingCancelView(APIView):
    """Cancel a PENDING or CONFIRMED booking and restore availability."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            with transaction.atomic():
                booking = Booking.objects.select_for_update().get(
                    pk=pk, user=request.user
                )

                if booking.status == 'CANCELLED':
                    record_flow('booking_cancel', 'rejected', booking_id=pk, reason='already_cancelled')
                    return Response(
                        {'error': 'Booking is already cancelled.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                if booking.status == 'PAID':
                    record_flow('booking_cancel', 'rejected', booking_id=pk, reason='paid_requires_refund')
                    return Response(
                        {'error': 'Paid bookings must be refunded, not cancelled.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # F-016: delegate inventory restoration to the single
                # authoritative implementation in BookingService. The caller
                # (this block) already satisfies release_inventory's two
                # preconditions — the booking row is locked via
                # select_for_update above, and the release happens in the
                # same transaction as the status change to CANCELLED, so a
                # second release can never free a vehicle that another
                # booking has since taken.
                BookingService.release_inventory(booking)

                booking.status = 'CANCELLED'
                booking.save(update_fields=['status'])

            response = Response(
                BookingSerializer(booking).data,
                status=status.HTTP_200_OK
            )
            record_flow('booking_cancel', 'success', booking_id=pk)
            return response
        except Booking.DoesNotExist:
            record_flow('booking_cancel', 'rejected', booking_id=pk, reason='not_found')
            return Response(
                {'error': 'Booking not found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception:
            record_flow('booking_cancel', 'failure', booking_id=pk, reason='unexpected', exc_info=True)
            raise
