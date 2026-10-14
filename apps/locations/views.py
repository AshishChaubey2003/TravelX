from django.db.models import Count, Q
from rest_framework import generics
from rest_framework.permissions import AllowAny
from .models import City
from .serializers import CitySerializer

class CityListView(generics.ListAPIView):
    serializer_class = CitySerializer
    permission_classes = [AllowAny]
    authentication_classes = []

    def get_queryset(self):
        # The serializer's hotel_count / adventure_count used to issue one
        # COUNT per city per field (26 queries for 12 cities). Annotating
        # them here makes it 2 queries total - the same numbers, far fewer
        # round-trips, which matters because the production database is a
        # remote managed instance. distinct=True is required: counting two
        # multi-valued relations in one query joins both, and without it
        # each count would be multiplied by the other relation's row count.
        # order_by('name') is explicit on purpose: annotating adds a GROUP BY,
        # which drops City.Meta.ordering and would return cities in an
        # arbitrary order (and make pagination unstable). Keeping it here
        # preserves exactly the alphabetical order clients saw before.
        queryset = City.objects.annotate(
            annotated_hotel_count=Count(
                'hotels', filter=Q(hotels__is_active=True), distinct=True
            ),
            annotated_adventure_count=Count(
                'adventures', filter=Q(adventures__is_active=True), distinct=True
            ),
        ).order_by('name')
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset