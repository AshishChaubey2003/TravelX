"""Regression tests for RegisterSerializer input validation (audit fix 2)."""
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.serializers import RegisterSerializer

STRONG = 'Tr@vel-Zebra-92'


def make(**overrides):
    data = {'username': 'new_traveler', 'email': 'new_traveler@example.com', 'password': STRONG}
    data.update(overrides)
    return data


class RegisterSerializerValidationTests(TestCase):
    def assertRejected(self, data, field):
        s = RegisterSerializer(data=data)
        self.assertFalse(s.is_valid())
        self.assertIn(field, s.errors)

    def test_strong_input_is_still_accepted(self):
        s = RegisterSerializer(data=make())
        self.assertTrue(s.is_valid(), s.errors)

    def test_missing_email_is_rejected(self):
        data = make()
        del data['email']
        self.assertRejected(data, 'email')

    def test_blank_email_is_rejected(self):
        self.assertRejected(make(email=''), 'email')

    def test_all_digit_password_is_rejected(self):
        self.assertRejected(make(password='12345678'), 'password')

    def test_common_password_is_rejected(self):
        self.assertRejected(make(password='password'), 'password')

    def test_password_matching_username_is_rejected(self):
        self.assertRejected(make(password='new_traveler'), 'password')


class RegisterEndpointValidationTests(TestCase):
    URL = '/api/v1/auth/register/'

    def test_missing_email_is_a_400_and_creates_no_account(self):
        data = make()
        del data['email']
        response = APIClient().post(self.URL, data, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_weak_password_is_a_400_and_creates_no_account(self):
        response = APIClient().post(self.URL, make(password='12345678'), format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)