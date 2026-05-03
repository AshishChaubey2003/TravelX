# ✈ TravelX — Event-Driven Travel Booking Backend

![TravelX Banner](https://images.unsplash.com/photo-1488646953014-85cb44e25828?w=1200&q=80)

> A production-ready, event-driven travel booking backend built with Django, DRF, Kafka, Redis, Celery, Razorpay, and Docker.

---

## 🚀 Live Demo

🌐 **Frontend**: [Coming Soon]  
🔗 **Backend API**: [Coming Soon]  
📦 **GitHub**: [https://github.com/AshishChaubey2003/TravelX](https://github.com/AshishChaubey2003/TravelX)

---

## 🧠 Project Overview

TravelX is a scalable, production-ready travel booking backend that allows users to:

- 🔍 **Search locations** — cities like Goa, Manali, Delhi, Mumbai
- 🏨 **View hotels** with pricing, ratings, and amenities
- 🧗 **Book adventures** — paragliding, trekking, water sports
- 🚗 **Rent vehicles** — bikes, cars, scooters
- 💳 **Pay online** — Razorpay integration with HMAC-SHA256 signature verification
- 📧 **OTP Email Verification** — Gmail SMTP with 10-minute expiry via Celery
- 📬 **Event-Driven Notifications** — Kafka-powered booking & payment events

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
| **Apache Kafka** | Event-driven architecture |
| **Razorpay** | Payment processing |

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
- Enables horizontal scaling of individual consumer groups

---

## 📊 Database Schema

```
City ──────┬──► Hotel
           ├──► Adventure  
           └──► Vehicle

User ──────┬──► Booking ──► BookingItem (price_at_booking snapshot)
           └──► Payment ──► Razorpay Integration
```

### Key Design Decisions
- `price_at_booking` — Snapshot price to prevent price drift
- `select_for_update()` — Prevent race conditions on inventory
- `transaction.atomic()` — All-or-nothing booking creation
- HMAC-SHA256 signature verification — Razorpay webhook security
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
POST /api/v1/auth/register/       Register user + OTP email
POST /api/v1/auth/verify-otp/     Verify OTP
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
POST /api/v1/payments/create-order/   Create Razorpay order
POST /api/v1/payments/verify/         Verify payment signature
POST /api/v1/payments/webhook/        Razorpay webhook
```

---

## 🚀 Quick Start

### Prerequisites
- Docker + Docker Compose
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

### 3. Start with Docker
```bash
docker-compose up --build
```

### 4. Create superuser
```bash
docker-compose exec web python manage.py createsuperuser
```

### 5. Open in browser
- Backend API: http://localhost:8000
- Admin Panel: http://localhost:8000/admin
- Swagger Docs: http://localhost:8000/api/docs/

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

# Razorpay
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=your_secret...

# Email (Gmail SMTP)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your@gmail.com
EMAIL_HOST_PASSWORD=your_app_password

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
│   ├── accounts/       # JWT auth + OTP verification
│   ├── locations/      # City model + API
│   ├── hotels/         # Hotel listings
│   ├── adventures/     # Adventure packages
│   ├── vehicles/       # Vehicle rentals
│   ├── bookings/       # Booking system
│   ├── payments/       # Razorpay integration
│   └── kafka_events/   # Kafka producers + consumers
├── config/             # Django settings
├── tasks/              # Celery tasks
└── docker-compose.yml
```

---

## 🎯 Key Features Implemented

- ✅ **Race condition prevention** — `select_for_update()` + `transaction.atomic()`
- ✅ **Price snapshot** — `price_at_booking` stored at booking time
- ✅ **Secure payments** — Razorpay HMAC-SHA256 signature verification
- ✅ **Event-driven** — Kafka topics for booking + payment events
- ✅ **Redis caching** — 3 isolated DBs (cache, session, broker) with TTL
- ✅ **JWT authentication** — Access + refresh token rotation + RBAC
- ✅ **OTP verification** — Email OTP via Gmail SMTP, 10-min expiry
- ✅ **Async tasks** — Celery for emails + background jobs
- ✅ **Containerized** — Full Docker Compose setup (Django + Nginx + PostgreSQL + Redis + Kafka + Celery)
- ✅ **Swagger docs** — Auto-generated API documentation

---

## 👨‍💻 Author

**Ashish Kumar Chaubey**  
Python Backend Developer | Django | FastAPI | System Design

[![GitHub](https://img.shields.io/badge/GitHub-AshishChaubey2003-black?logo=github)](https://github.com/AshishChaubey2003)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-blue?logo=linkedin)](https://linkedin.com/in/your-profile)

---

## 📄 License

MIT License — feel free to use this project for learning and portfolio purposes.

---

⭐ **If you found this helpful, please star the repo!**
