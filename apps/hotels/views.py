from rest_framework import generics
from rest_framework.permissions import AllowAny
from .models import Hotel
from .serializers import HotelListSerializer, HotelDetailSerializer

class HotelListView(generics.ListAPIView):
    serializer_class = HotelListSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = Hotel.objects.filter(is_active=True).select_related('city')
        city_id = self.request.query_params.get('city')
        price_min = self.request.query_params.get('price_min')
        price_max = self.request.query_params.get('price_max')
        if city_id:
            queryset = queryset.filter(city_id=city_id)
        if price_min:
            queryset = queryset.filter(price_per_night__gte=price_min)
        if price_max:
            queryset = queryset.filter(price_per_night__lte=price_max)
        return queryset

class HotelDetailView(generics.RetrieveAPIView):
    serializer_class = HotelDetailSerializer
    permission_classes = [AllowAny]
    queryset = Hotel.objects.filter(is_active=True)