from rest_framework import generics
from rest_framework.permissions import AllowAny
from .models import Adventure
from .serializers import AdventureSerializer

class AdventureListView(generics.ListAPIView):
    serializer_class = AdventureSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = Adventure.objects.filter(is_active=True).select_related('city')
        city_id = self.request.query_params.get('city')
        if city_id:
            queryset = queryset.filter(city_id=city_id)
        return queryset

class AdventureDetailView(generics.RetrieveAPIView):
    serializer_class = AdventureSerializer
    permission_classes = [AllowAny]
    queryset = Adventure.objects.filter(is_active=True)