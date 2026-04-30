from groq import Groq
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from apps.locations.models import City
from apps.hotels.models import Hotel
from apps.adventures.models import Adventure
from apps.vehicles.models import Vehicle

client = Groq(api_key=settings.GROQ_API_KEY)


def get_cities():
    try:
        cities = City.objects.filter(is_active=True).values('id', 'name', 'state')
        return [{'id': str(c['id']), 'name': c['name'], 'state': c['state']} for c in cities]
    except:
        return []


def get_hotels(city_id):
    try:
        hotels = Hotel.objects.filter(city_id=city_id, is_active=True).values('id', 'name', 'price_per_night', 'rating', 'available_rooms')
        return [{'id': str(h['id']), 'name': h['name'], 'price_per_night': str(h['price_per_night']), 'rating': h['rating'], 'available_rooms': h['available_rooms']} for h in hotels]
    except:
        return []


def get_adventures(city_id):
    try:
        adventures = Adventure.objects.filter(city_id=city_id, is_active=True).values('id', 'name', 'price_per_person', 'duration_hours', 'difficulty')
        return [{'id': str(a['id']), 'name': a['name'], 'price_per_person': str(a['price_per_person']), 'duration_hours': a['duration_hours'], 'difficulty': a['difficulty']} for a in adventures]
    except:
        return []


def get_vehicles(city_id):
    try:
        vehicles = Vehicle.objects.filter(city_id=city_id, is_available=True).values('id', 'name', 'price_per_day', 'vehicle_type')
        return [{'id': str(v['id']), 'name': v['name'], 'price_per_day': str(v['price_per_day']), 'vehicle_type': v['vehicle_type']} for v in vehicles]
    except:
        return []


class PlanTripView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        query = request.data.get('query', '')
        session = request.data.get('session', {})

        if not query:
            return Response({'error': 'Query required'}, status=400)

        try:
            cities = get_cities()
            matched_city = None
            for city in cities:
                if city['name'].lower() in query.lower():
                    matched_city = city
                    break

            if not matched_city and session.get('city_id'):
                for city in cities:
                    if str(city['id']) == str(session.get('city_id')):
                        matched_city = city
                        break

            step = session.get('step', 'initial')
            hotels, adventures, vehicles = [], [], []

            if matched_city:
                hotels = get_hotels(matched_city['id'])
                adventures = get_adventures(matched_city['id'])
                vehicles = get_vehicles(matched_city['id'])

            # Step 1: City detected → ask hotel
            if matched_city and step == 'initial':
                if not hotels:
                    return Response({
                        'response': f"I found {matched_city['name']} but no hotels are available yet. Try another city!",
                        'options': [],
                        'session': {'step': 'initial'},
                        'type': 'text'
                    })
                return Response({
                    'response': f"Great choice! 🌴 Let's plan your **{matched_city['name']}** trip!\n\nWhich hotel would you like to stay at?",
                    'options': [{'label': f"{h['name']} — ₹{h['price_per_night']}/night", 'value': h['id'], 'name': h['name'], 'price': h['price_per_night']} for h in hotels[:4]],
                    'session': {'step': 'select_hotel', 'city_id': matched_city['id'], 'city_name': matched_city['name']},
                    'type': 'options'
                })

            # Step 2: Hotel selected → ask adventures
            elif step == 'select_hotel':
                selected_hotel = {'id': query, 'name': session.get('option_name', ''), 'price': session.get('option_price', 0)}
                if not adventures:
                    return Response({
                        'response': "Nice pick! 🏨 No adventures available. Let's pick a vehicle!",
                        'options': [{'label': '🚶 No vehicle needed', 'value': 'skip'}] + [{'label': f"{v['name']} — ₹{v['price_per_day']}/day", 'value': v['id'], 'name': v['name'], 'price': v['price_per_day']} for v in vehicles[:4]],
                        'session': {**session, 'step': 'select_vehicle', 'selected_hotel': selected_hotel},
                        'type': 'options'
                    })
                return Response({
                    'response': "Nice pick! 🏨 Now choose your adventures:",
                    'options': [{'label': f"{a['name']} — ₹{a['price_per_person']}/person | {a['duration_hours']}h", 'value': a['id'], 'name': a['name'], 'price': a['price_per_person']} for a in adventures[:4]] + [{'label': '✅ Done selecting adventures', 'value': 'done', 'name': 'Done'}],
                    'session': {**session, 'step': 'select_adventure', 'selected_hotel': selected_hotel},
                    'type': 'options'
                })

            # Step 3: Adventure selected → ask vehicles
            elif step == 'select_adventure':
                if query == 'done' or query == 'skip':
                    if not vehicles:
                        return generate_final_plan(session, matched_city)
                    return Response({
                        'response': "Great choices! 🧗 Now pick a vehicle:",
                        'options': [{'label': f"{v['name']} — ₹{v['price_per_day']}/day | {v['vehicle_type']}", 'value': v['id'], 'name': v['name'], 'price': v['price_per_day']} for v in vehicles[:4]] + [{'label': '🚶 No vehicle needed', 'value': 'skip'}],
                        'session': {**session, 'step': 'select_vehicle'},
                        'type': 'options'
                    })
                else:
                    adv_list = session.get('selected_adventures', [])
                    adv_list.append({'id': query, 'name': session.get('option_name', ''), 'price': session.get('option_price', 0)})
                    return Response({
                        'response': "Added! 🎯 Want to add more adventures or done?",
                        'options': [{'label': f"{a['name']} — ₹{a['price_per_person']}/person | {a['duration_hours']}h", 'value': a['id'], 'name': a['name'], 'price': a['price_per_person']} for a in adventures[:4]] + [{'label': '✅ Done selecting adventures', 'value': 'done', 'name': 'Done'}],
                        'session': {**session, 'step': 'select_adventure', 'selected_adventures': adv_list},
                        'type': 'options'
                    })

            # Step 4: Vehicle selected → Final plan
            elif step == 'select_vehicle':
                if query != 'skip':
                    session['selected_vehicle'] = {'id': query, 'name': session.get('option_name', ''), 'price': session.get('option_price', 0)}
                return generate_final_plan(session, matched_city)

            # Fallback
            else:
                city_names = [c['name'] for c in cities]
                return Response({
                    'response': f"I can help you plan trips to: **{', '.join(city_names)}**\n\nJust tell me your destination and budget! 🗺️",
                    'options': [{'label': f"Plan {c} trip", 'value': f"Plan {c} trip"} for c in city_names[:4]],
                    'session': {'step': 'initial'},
                    'type': 'options'
                })

        except Exception as e:
            return Response({
                'response': f'AI error: {str(e)}',
                'session': {'step': 'initial'},
                'type': 'text'
            }, status=200)


def generate_final_plan(session, city):
    hotel = session.get('selected_hotel', {})
    adventures = session.get('selected_adventures', [])
    vehicle = session.get('selected_vehicle', {})
    city_name = session.get('city_name', 'your destination')

    nights = 2
    hotel_cost = float(hotel.get('price', 0)) * nights
    adv_cost = sum(float(a.get('price', 0)) for a in adventures)
    vehicle_cost = float(vehicle.get('price', 0)) * nights if vehicle else 0
    total = hotel_cost + adv_cost + vehicle_cost

    plan = f"🏙️ **YOUR TRIP PLAN — {city_name.upper()}**\n"
    plan += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    plan += f"🏨 **Hotel:** {hotel.get('name', 'N/A')} × {nights} nights\n"

    if adventures:
        plan += "\n🧗 **Adventures:**\n"
        for a in adventures:
            plan += f"  • {a.get('name', '')}\n"

    if vehicle:
        plan += f"\n🚗 **Vehicle:** {vehicle.get('name', '')} × {nights} days\n"

    plan += "\n💰 **Price Breakdown:**\n"
    plan += f"  • Hotel: ₹{hotel.get('price', 0)} × {nights} nights = ₹{hotel_cost:,.0f}\n"
    if adventures:
        plan += f"  • Adventures: ₹{adv_cost:,.0f}\n"
    if vehicle:
        plan += f"  • Vehicle: ₹{vehicle.get('price', 0)} × {nights} days = ₹{vehicle_cost:,.0f}\n"
    plan += f"\n  **Total: ₹{total:,.0f}**\n\n"
    plan += "✅ **Ready to book?** Head to the Explore section to confirm your bookings!"

    return Response({
        'response': plan,
        'options': [
            {'label': '🔄 Plan another trip', 'value': 'restart'},
            {'label': '🗺️ Explore more cities', 'value': 'explore'}
        ],
        'session': {'step': 'done'},
        'type': 'final'
    })