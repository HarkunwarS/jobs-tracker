import unittest
from sources.approval import approved


class ProductionActivationTests(unittest.TestCase):
    def test_channel_follows_config(self):
        on = {'runtime': {'mode': 'production'}, 'notifications': {'email': {'enabled': True}, 'telegram': {'enabled': True}}}
        self.assertTrue(approved('email', on))
        self.assertTrue(approved('telegram', on))

    def test_staging_and_disabled_never_send(self):
        staging = {'runtime': {'mode': 'staging'}, 'notifications': {'email': {'enabled': True}}}
        off = {'runtime': {'mode': 'production'}, 'notifications': {'email': {'enabled': False}}}
        self.assertFalse(approved('email', staging))
        self.assertFalse(approved('email', off))

    def test_events_stay_off_and_unknown_channels_denied(self):
        cfg = {'runtime': {'mode': 'production'}, 'notifications': {'events_email': {'enabled': False}}}
        self.assertFalse(approved('events_email', cfg))
        self.assertFalse(approved('sms', {'runtime': {'mode': 'production'}, 'notifications': {'sms': {'enabled': True}}}))
