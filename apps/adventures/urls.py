from django.urls import path
from .views import AdventureListView, AdventureDetailView

urlpatterns = [
    path('', AdventureListView.as_view(), name='adventure-list'),
    path('<uuid:pk>/', AdventureDetailView.as_view(), name='adventure-detail'),
]