# ✈ TravelX — AI Powered Travel Booking Platform

![TravelX Banner](https://images.unsplash.com/photo-1488646953014-85cb44e25828?w=1200&q=80)

> A production-ready, full-stack AI-powered travel booking platform built with Django, React, Kafka, Redis, Celery, and Stripe.

---

## 🚀 Live Demo

🌐 **Frontend**: [Coming Soon]  
🔗 **Backend API**: [Coming Soon]  
📦 **GitHub**: [https://github.com/AshishChaubey2003/TravelX](https://github.com/AshishChaubey2003/TravelX)

---

## 📸 Screenshots

| Home Page | Explore Page | Booking Flow |
|-----------|--------------|--------------|
| ![Home](https://via.placeholder.com/300x200) | ![Explore](https://via.placeholder.com/300x200) | ![Booking](https://via.placeholder.com/300x200) |

---

## 🧠 Project Overview

TravelX is a scalable, production-ready travel booking platform that allows users to:

- 🔍 **Search locations** — cities like Goa, Manali, Delhi, Mumbai
- 🏨 **View hotels** with pricing, ratings, and amenities
- 🧗 **Book adventures** — paragliding, trekking, water sports
- 🚗 **Rent vehicles** — bikes, cars, scooters
- 🗺 **Interactive map** — Leaflet.js + OpenStreetMap with distance
- 💳 **Pay online** — Stripe Checkout integration
- 🤖 **AI trip planner** — Natural language trip planning with Gemini AI

---

## ⚙️ Tech Stack

### Backend
| Technology | Purpose |
|------------|---------|
| **Django 5.0** | Web framework |
| **Django REST Framework** | REST API |
| **PostgreSQL** | Primary database |
| **Redis** | Caching + Session + Celery broker |
| **Celery** | Async task processing |
| **Kafka** | Event-driven architecture |
| **Stripe** | Payment processing |
| **Gemini AI** | AI trip planning |

### Frontend
| Technology | Purpose |
|------------|---------|
| **React 18** | UI framework |
| **React Router** | Client-side routing |
| **Axios** | HTTP client |
| **Leaflet.js** | Interactive maps |
| **React Hot Toast** | Notifications |

### DevOps
| Technology | Purpose |
|------------|---------|
| **Docker + Docker Compose** | Containerization |
| **Gunicorn** | WSGI server |
| **Nginx** | Reverse proxy |

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    React Frontend                        │
│              (localhost:3000)                           │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTP / REST API
┌─────────────────────▼───────────────────────────────────┐
│                 Nginx (Reverse Proxy)                    │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│            Django + Gunicorn (localhost:8000)           │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ Locations│  │  Hotels  │  │Bookings  │             │
│  │   API    │  │   API    │  │   API    │             │
│  └──────────┘  └──────────┘  └──────────┘             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │Adventures│  │ Vehicles │  │Payments  │             │
│  │   API    │  │   API    │  │   API    │             │
│  └──────────┘  └──────────┘  └──────────┘             │
└────┬──────────────┬──────────────┬───────────────────┘
     │              │              │
┌────▼────┐   ┌─────▼────┐  ┌────▼────┐
│PostgreSQL│   │  Redis   │  │  Kafka  │
│   DB    │   │  Cache   │  │ Events  │
└─────────┘   └──────────┘  └─────────┘
                    │
              ┌─────▼────┐
              │  Celery  │
              │ Workers  │
              └──────────┘
```

---

## ⚡ Kafka Event-Driven Architecture

```
Booking Service ──► booking.created ──► Email Consumer (Celery)
                                    ──► Analytics Consumer
                                    ──► Inventory Consumer

Payment Webhook ──► payment.success ──► Booking Status Update
                                    ──► Confirmation Email

User Action ────► booking.cancelled ──► Refund Flow
                                    ──► Inventory Release
```

**Why Kafka?**
- Decouples booking service from downstream consumers
- Events are durable — if email service crashes, it catches up on restart
- New consumers can subscribe without touching booking code
- Enables horizontal scaling of individual services

---

## 📊 Database Schema

```
City ──────┬──► Hotel
           ├──► Adventure  
           └──► Vehicle

User ──────┬──► Booking ──► BookingItem (price_at_booking snapshot)
           └──► Payment ──► Stripe Integration
```

### Key Design Decisions
- `price_at_booking` — Snapshot price to prevent price drift
- `idempotency_key` — Stripe deduplication
- `select_for_update()` — Prevent race conditions on inventory
- `transaction.atomic()` — All-or-nothing booking creation
- Indexes on `city`, `status`, `user` for fast queries

---

## 🔴 Redis Caching Strategy

```python
# Cache keys
hotels:city:{city_id}      TTL: 15 min
adventures:city:{city_id}  TTL: 15 min
cities:all                 TTL: 1 hour
hotel:{hotel_id}           TTL: 30 min

# Redis databases
db=0  →  API Cache
db=1  →  Session Store
db=2  →  Celery Broker
```

---

## 🔌 API Endpoints

### Auth
```
POST /api/v1/auth/register/       Register user
POST /api/v1/auth/token/          Login (JWT)
POST /api/v1/auth/token/refresh/  Refresh token
```

### Locations
```
GET /api/v1/cities/               List all cities
GET /api/v1/hotels/?city={id}     Hotels by city
GET /api/v1/adventures/?city={id} Adventures by city
GET /api/v1/vehicles/?city={id}   Vehicles by city
```

### Bookings
```
POST /api/v1/bookings/            Create booking
GET  /api/v1/bookings/my/         My bookings
GET  /api/v1/bookings/{id}/       Booking detail
```

### Payments
```
POST /api/v1/payments/create-checkout/  Create Stripe session
POST /api/v1/payments/webhook/          Stripe webhook
```

### AI Agent
```
POST /api/v1/ai/plan/             Plan trip with AI
```

---

## 🚀 Quick Start

### Prerequisites
- Docker + Docker Compose
- Node.js 18+
- Git

### 1. Clone the repository
```bash
git clone https://github.com/AshishChaubey2003/TravelX.git
cd TravelX
```

### 2. Setup environment variables
```bash
cp .env.example .env
# Edit .env with your keys
```

### 3. Start backend with Docker
```bash
docker-compose up --build
```

### 4. Create superuser
```bash
docker-compose exec web python manage.py createsuperuser
```

### 5. Start React frontend
```bash
cd frontend
npm install
npm start
```

### 6. Open in browser
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- Admin Panel: http://localhost:8000/admin

---

## 🔑 Environment Variables

```env
# Django
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DATABASE_URL=postgresql://user:pass@db:5432/travelx_db

# Redis
REDIS_URL=redis://redis:6379/0

# Kafka
KAFKA_BROKER=kafka:29092

# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PUBLISHABLE_KEY=pk_test_...

# AI
GEMINI_API_KEY=your_gemini_key

# Celery
CELERY_BROKER_URL=redis://redis:6379/2
CELERY_RESULT_BACKEND=redis://redis:6379/2
```

---

## 📁 Project Structure

```
travelx/
├── apps/
│   ├── core/           # Base models, utilities
│   ├── accounts/       # JWT auth
│   ├── locations/      # City model + API
│   ├── hotels/         # Hotel listings
│   ├── adventures/     # Adventure packages
│   ├── vehicles/       # Vehicle rentals
│   ├── bookings/       # Booking system
│   ├── payments/       # Stripe integration
│   ├── kafka_events/   # Kafka producers + consumers
│   └── ai_agent/       # AI trip planner
├── config/             # Django settings
├── frontend/           # React application
│   └── src/
│       ├── components/ # Reusable components
│       ├── pages/      # Page components
│       └── context/    # React context
├── docker/             # Docker + Nginx config
├── tasks/              # Celery tasks
└── docker-compose.yml
```

---

## 🎯 Key Features Implemented

- ✅ **Race condition prevention** — `select_for_update()` + `transaction.atomic()`
- ✅ **Price snapshot** — `price_at_booking` stored at booking time
- ✅ **Idempotent payments** — Stripe webhook deduplication
- ✅ **Event-driven** — Kafka topics for booking + payment events
- ✅ **Redis caching** — City/hotel listings cached with TTL
- ✅ **JWT authentication** — Access + refresh token flow
- ✅ **Async tasks** — Celery for emails + background jobs
- ✅ **Interactive map** — Leaflet.js with hotel/adventure markers
- ✅ **AI chat** — Natural language trip planning
- ✅ **Containerized** — Full Docker Compose setup

---

## 👨‍💻 Author

**Ashish Chaubey**  
Backend Developer | Django | Python | System Design

[![GitHub](https://img.shields.io/badge/GitHub-AshishChaubey2003-black?logo=github)](https://github.com/AshishChaubey2003)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-blue?logo=linkedin)](https://linkedin.com/in/your-profile)

---

## 📄 License

MIT License — feel free to use this project for learning and portfolio purposes.

---

⭐ **If you found this helpful, please star the repo!**
