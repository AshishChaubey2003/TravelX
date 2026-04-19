from django.urls import path
from .views import CityListView

urlpatterns = [
    path('', CityListView.as_view(), name='city-list'),
]