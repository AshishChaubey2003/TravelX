import axios from "axios";

// FE-007: In a production build (`npm run build`), REACT_APP_API_URL MUST be
// set. A missing value used to silently fall through to the localhost default,
// which caused prod deployments to look like the backend was dead (every
// request got ECONNREFUSED against the user's own machine). Hard-failing at
// module load surfaces the misconfiguration immediately. In development the
// localhost fallback is kept so `npm start` works out of the box.
const _envApiUrl = process.env.REACT_APP_API_URL;
if (!_envApiUrl && process.env.NODE_ENV === "production") {
  throw new Error(
    "REACT_APP_API_URL is required for production builds. " +
      "Set it in the environment before running `npm run build`."
  );
}

const API = axios.create({
  baseURL: _envApiUrl || "http://localhost:8000/api/v1",
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
