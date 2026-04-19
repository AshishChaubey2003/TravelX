from rest_framework import generics
from rest_framework.permissions import AllowAny
from .models import Vehicle
from .serializers import VehicleSerializer

class VehicleListView(generics.ListAPIView):
    serializer_class = VehicleSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = Vehicle.objects.filter(is_available=True).select_related('city')
        city_id = self.request.query_params.get('city')
        if city_id:
            queryset = queryset.filter(city_id=city_id)
        return queryset

class VehicleDetailView(generics.RetrieveAPIView):
    serializer_class = VehicleSerializer
    permission_classes = [AllowAny]
    queryset = Vehicle.objects.all()