import axios from "axios";

const API = axios.create({
  baseURL: process.env.REACT_APP_API_URL || "http://localhost:8000/api/v1",
});

// Attach token to every request (if present)
API.interceptors.request.use((config) => {
  const token = localStorage.getItem("tx_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// If any request returns 401, the token is invalid/expired -> remove it
// so public endpoints (cities, hotels, adventures, vehicles) work again.
API.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      localStorage.removeItem("tx_token");
    }
    return Promise.reject(error);
  },
);

export const getCities = () => API.get("/cities/");
export const getCity = (id) => API.get(`/cities/${id}/`);
export const getHotels = (cityId) => API.get(`/hotels/?city=${cityId}`);
export const getAdventures = (cityId) => API.get(`/adventures/?city=${cityId}`);
export const getVehicles = (cityId) => API.get(`/vehicles/?city=${cityId}`);
export const login = (data) => API.post("/auth/token/", data);
export const register = (data) => API.post("/auth/register/", data);
export const createBooking = (data) => API.post("/bookings/", data);
export const createCheckout = (bookingId) =>
  API.post("/payments/create-checkout/", { booking_id: bookingId });
export const planTrip = (payload) => API.post("/ai/plan/", payload);

export default API;
