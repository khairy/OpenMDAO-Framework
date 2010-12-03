"""
Test Role-Based Access Control (RBAC).
"""

import inspect
import logging
import os
import socket
import sys
import threading
import unittest
import nose

from openmdao.main.rbac import Credentials, get_credentials, set_credentials, \
                               need_proxy, rbac, rbac_methods, check_role, \
                               AccessController, RoleError

from openmdao.util.testutil import assert_raises


class ProxyRequired(object):
    """ Just a class to be proxied. """
    pass


class Object(object):
    """ Just a class for exercising RBAC. """

    def no_rbac(self):
        """ No RBAC assigned. """
        return None

    @rbac('owner')
    def single_role(self):
        """ Just a single role assigned. """
        return None

    @rbac(('owner', 'user'))
    def multi_role(self):
        """ Multiple roles assigned. """
        return None

    @rbac('*')
    def role_pattern(self):
        """ Role pattern assigned. """
        return None

    @rbac('*', 'owner')
    def proxy_role(self):
        """ To be executed with role 'owner'. """
        return None

    @rbac('*', 'other')
    def proxy_other(self):
        """ To be executed with role 'other'. """
        return None

    @rbac('*', proxy_types=[ProxyRequired])
    def proxy_result(self):
        """ To be executed with role 'owner'. """
        return None


class TestCase(unittest.TestCase):
    """ Test RBAC. """

    def test_credentials(self):
        logging.debug('')
        logging.debug('test_credentials')

        # Basic form.
        owner = Credentials()
        self.assertEqual('%s' % owner, owner.user)

        # Comparison.
        user = Credentials()
        self.assertEqual(user, owner)
        user.user = 'anyone@hostname'
        self.assertNotEqual(user, owner)

        # Thread storage.
        try:
            del threading.current_thread().credentials  # Ensure empty.
        except AttributeError:
            pass
        self.assertEqual(get_credentials(), None)
        set_credentials(owner)
        self.assertEqual(get_credentials(), owner)

    def test_decorator(self):
        logging.debug('')
        logging.debug('test_decorator')

        # Decorated methods.
        obj = Object()
        methods = [name for name in dir(obj)
                                 if inspect.ismethod(getattr(obj, name))]
        methods.remove('no_rbac')
        self.assertEqual(sorted(rbac_methods(obj)), sorted(methods))

        # Result proxying.
        normal_value = object()
        proxy_value = ProxyRequired()
        self.assertFalse(need_proxy(obj.no_rbac, proxy_value))
        self.assertFalse(need_proxy(obj.single_role, normal_value))
        self.assertFalse(need_proxy(obj.proxy_result, normal_value))
        self.assertTrue(need_proxy(obj.proxy_result, proxy_value))

        # Access checking.
        assert_raises(self, "check_role('owner', obj.no_rbac)",
                      globals(), locals(), RoleError,
                      'No RBAC for function!')

        assert_raises(self, "check_role('xyzzy', obj.single_role)",
                      globals(), locals(), RoleError,
                      "No access for role 'xyzzy'")

        check_role('owner', obj.multi_role)
        check_role('user',  obj.multi_role)
        check_role('xyzzy', obj.role_pattern)

    def test_access_controller(self):
        logging.debug('')
        logging.debug('test_access_controller')

        # Credential-to-role mapping.
        set_credentials(None)
        assert_raises(self, 'AccessController()', globals(), locals(),
                      RoleError, 'No current credentials')

        owner = Credentials()
        set_credentials(owner)
        controller = AccessController()
        self.assertEqual(controller.get_role(None), '')
        self.assertEqual(controller.get_role(owner), 'owner')
        user = Credentials()
        user.user = 'anyone@hostname'
        self.assertEqual(controller.get_role(user), 'user')
        assert_raises(self, 'controller.get_role(object())', globals(), locals(),
                      TypeError, 'credentials is not a Credentials object')

        # Proxy role-to-credential mapping.
        obj = Object()
        assert_raises(self, 'controller.get_proxy_credentials(obj.no_rbac, user)',
                      globals(), locals(), RoleError, 'No RBAC for method')
        self.assertEqual(controller.get_proxy_credentials(obj.single_role, user),
                         user)
        self.assertEqual(controller.get_proxy_credentials(obj.proxy_role, user),
                         owner)
        assert_raises(self,
                      'controller.get_proxy_credentials(obj.proxy_other, user)',
                      globals(), locals(), RoleError,
                      'No credentials for proxy role other')
        assert_raises(self, "controller.set_proxy_credentials('other', object())",
                      globals(), locals(), TypeError,
                      'credentials is not a Credentials object')
        other = Credentials()
        other.user = 'floyd@nowheresville'
        controller.set_proxy_credentials('other', other)
        self.assertEqual(controller.get_proxy_credentials(obj.proxy_other, user),
                         other)

        # Attribute access.
        controller.check_access('user', '__getattr__', obj, 'dummy')
        controller.check_access('owner', '__setattr__', obj, 'dummy')
        assert_raises(self,
                      "controller.check_access('user', '__delattr__', obj, 'dummy')",
                      globals(), locals(), RoleError,
                      "No __delattr__ access to 'dummy' by role 'user'")
        assert_raises(self,
                      "controller.check_access('', '__getattr__', obj, 'dummy')",
                      globals(), locals(), RoleError, 'No access by null role')

        # Attribute proxying.
        proxy_value = ProxyRequired()
        self.assertFalse(controller.need_proxy(obj, 'dummy', proxy_value))
        controller.attr_proxy_required(obj, 'dummy')
        self.assertTrue(controller.need_proxy(obj, 'dummy', proxy_value))
        controller.attr_proxy_required(obj, 'dummy', False)
        self.assertFalse(controller.need_proxy(obj, 'dummy', proxy_value))
        controller.class_proxy_required(ProxyRequired)
        self.assertTrue(controller.need_proxy(obj, 'dummy', proxy_value))


if __name__ == '__main__':
    sys.argv.append('--cover-package=openmdao.main')
    sys.argv.append('--cover-erase')
    nose.runmodule()
