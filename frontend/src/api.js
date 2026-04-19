import axios from "axios";

const API = axios.create({
  baseURL: "http://localhost:8000/api/v1",
});

API.interceptors.request.use((config) => {
  const token = localStorage.getItem("tx_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export const getCities = () => API.get("/cities/");
export const getHotels = (cityId) => API.get(`/hotels/?city=${cityId}`);
export const getAdventures = (cityId) => API.get(`/adventures/?city=${cityId}`);
export const getVehicles = (cityId) => API.get(`/vehicles/?city=${cityId}`);
export const login = (data) => API.post("/auth/token/", data);
export const register = (data) => API.post("/auth/register/", data);
export const createBooking = (data) => API.post("/bookings/", data);
export const createCheckout = (bookingId) =>
  API.post("/payments/create-checkout/", { booking_id: bookingId });
export const planTrip = (query) => API.post("/ai/plan/", { query });

export default API;
