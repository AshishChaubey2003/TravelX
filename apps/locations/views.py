from rest_framework import generics
from rest_framework.permissions import AllowAny
from .models import City
from .serializers import CitySerializer

class CityListView(generics.ListAPIView):
    serializer_class = CitySerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = City.objects.filter(is_active=True)
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset