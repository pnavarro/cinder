# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Pedro Navarro Perez
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Unit tests for Windows Server 2012 OpenStack Cinder volume driver
"""


import os

from oslo.config import cfg

import mox as mox_lib
from mox import IgnoreArg
from mox import stubout

from cinder import test
from cinder.tests.windows import db_fakes
from cinder.volume.drivers.windows import windows
from cinder.volume.drivers.windows import windows_common


CONF = cfg.CONF


class TestWindowsDriver(test.TestCase):

    def __init__(self, method):
        super(TestWindowsDriver, self).__init__(method)

    def setUp(self):
        super(TestWindowsDriver, self).setUp()
        self._mox = mox_lib.Mox()
        self.stubs = stubout.StubOutForTesting()
        self.flags(
            windows_iscsi_lun_path='C:\iSCSIVirtualDisks',
        )
        self._setup_stubs()

        self._driver = windows.WindowsDriver()

    def tearDown(self):
        self._mox.UnsetStubs()
        self.stubs.UnsetAll()
        super(TestWindowsDriver, self).tearDown()

    def _setup_stubs(self):

        def fake_wcommon__init__(self):
            pass
        windows_common.WindowsCommon.__init__ = fake_wcommon__init__

    def fake_local_path(self, volume):
            return os.path.join(CONF.windows_iscsi_lun_path,
                                str(volume['name']) + ".vhd")

    def test_check_for_setup_errors(self):
        mox = self._mox
        drv = self._driver
        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'check_for_setup_error')
        windows_common.WindowsCommon.check_for_setup_error()

        mox.ReplayAll()

        drv.check_for_setup_error()

        mox.VerifyAll()

    def test_create_volume(self):
        mox = self._mox
        drv = self._driver
        volume = db_fakes.get_fake_volume_info()

        self.stubs.Set(drv, 'local_path', self.fake_local_path)

        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'create_volume')

        windows_common.WindowsCommon.create_volume(self.fake_local_path(volume),
                                                   volume['name'],
                                                   volume['size'])

        mox.ReplayAll()

        drv.create_volume(volume)

        mox.VerifyAll()

    def test_delete_volume(self):
        """delete_volume simple test case."""
        mox = self._mox
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()

        mox.StubOutWithMock(drv, 'local_path')
        drv.local_path(volume).AndReturn(self.fake_local_path(volume))

        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'delete_volume')
        windows_common.WindowsCommon.delete_volume(volume['name'],
                                                   self.fake_local_path(volume))
        mox.ReplayAll()

        drv.delete_volume(volume)

        mox.VerifyAll()

    def test_create_snapshot(self):
        mox = self._mox
        drv = self._driver
        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'create_snapshot')
        volume = db_fakes.get_fake_volume_info()
        snapshot = db_fakes.get_fake_snapshot_info()

        self.stubs.Set(drv, 'local_path', self.fake_local_path(snapshot))

        windows_common.WindowsCommon.create_snapshot(volume['name'],
                                                     snapshot['name'])

        mox.ReplayAll()

        drv.create_snapshot(snapshot)

        mox.VerifyAll()

    def test_create_volume_from_snapshot(self):
        mox = self._mox
        drv = self._driver

        snapshot = db_fakes.get_fake_snapshot_info()
        volume = db_fakes.get_fake_volume_info()

        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'create_volume_from_snapshot')
        windows_common.WindowsCommon.\
            create_volume_from_snapshot(volume['name'], snapshot['name'])

        mox.ReplayAll()

        drv.create_volume_from_snapshot(volume, snapshot)

        mox.VerifyAll()

    def test_delete_snapshot(self):
        mox = self._mox
        drv = self._driver

        snapshot = db_fakes.get_fake_snapshot_info()

        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'delete_snapshot')
        windows_common.WindowsCommon.delete_snapshot(snapshot['name'])

        mox.ReplayAll()

        drv.delete_snapshot(snapshot)

        mox.VerifyAll()

    def test_create_export(self):
        mox = self._mox
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()

        initiator_name = "%s%s" % (CONF.iscsi_target_prefix, volume['name'])

        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'create_iscsi_target')
        windows_common.WindowsCommon.create_iscsi_target(initiator_name,
                                                         IgnoreArg())
        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'add_disk_to_target')
        windows_common.WindowsCommon.add_disk_to_target(volume['name'],
                                                        initiator_name)

        mox.ReplayAll()

        export_info = drv.create_export(None, volume)

        mox.VerifyAll()

        self.assertEquals(export_info['provider_location'], initiator_name)

    def test_initialize_connection(self):
        mox = self._mox
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()
        initiator_name = "%s%s" % (CONF.iscsi_target_prefix, volume['name'])

        connector = db_fakes.get_fake_connector_info()

        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'associate_initiator_with_iscsi_target')
        windows_common.WindowsCommon.associate_initiator_with_iscsi_target(
            volume['provider_location'], initiator_name, )

        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'get_host_information')
        windows_common.WindowsCommon.get_host_information(
            volume, volume['provider_location'])

        mox.ReplayAll()

        drv.initialize_connection(volume, connector)

        mox.VerifyAll()

    def test_terminate_connection(self):
        mox = self._mox
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()
        initiator_name = "%s%s" % (CONF.iscsi_target_prefix, volume['name'])
        connector = db_fakes.get_fake_connector_info()

        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'delete_iscsi_target')
        windows_common.WindowsCommon.delete_iscsi_target(
            initiator_name, volume['provider_location'])

        mox.ReplayAll()

        drv.terminate_connection(volume, connector)

        mox.VerifyAll()

    def test_ensure_export(self):
        mox = self._mox
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()

        initiator_name = "%s%s" % (CONF.iscsi_target_prefix, volume['name'])

        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'create_iscsi_target')
        windows_common.WindowsCommon.create_iscsi_target(initiator_name,
                                                         True)
        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'add_disk_to_target')
        windows_common.WindowsCommon.add_disk_to_target(volume['name'],
                                                        initiator_name)

        mox.ReplayAll()

        drv.ensure_export(None, volume)

        mox.VerifyAll()

    def test_remove_export(self):
        mox = self._mox
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()

        target_name = volume['provider_location']

        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'remove_iscsi_target')
        windows_common.WindowsCommon.remove_iscsi_target(target_name)

        mox.ReplayAll()

        drv.remove_export(None, volume)

        mox.VerifyAll()

    def test_copy_image_to_volume(self):
        """resize_image common case usage."""
        mox = self._mox
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()

        self.stubs.Set(drv, 'local_path', self.fake_local_path)

        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'fetch_to_vhd')
        windows_common.WindowsCommon.fetch_to_vhd(None, None, None,
                                                  self.fake_local_path(volume))
        mox.ReplayAll()

        drv.copy_image_to_volume(None, volume, None, None)

        mox.VerifyAll()

    def test_copy_volume_to_image(self):
        mox = self._mox
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()

        self.stubs.Set(drv, 'local_path', self.fake_local_path)

        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'upload_volume')

        windows_common.WindowsCommon.upload_volume(None, None, None,
                                                   self.fake_local_path(volume))

        mox.ReplayAll()

        drv.copy_volume_to_image(None, volume, None, None)

        mox.VerifyAll()

    def test_create_cloned_volume(self):
        mox = self._mox
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()
        volume_cloned = db_fakes.get_fake_volume_info_cloned()

        self._mox.StubOutWithMock(windows_common.WindowsCommon, 'create_volume')

        windows_common.WindowsCommon.create_volume(IgnoreArg(), IgnoreArg(),
                                                   IgnoreArg())

        self._mox.StubOutWithMock(windows_common.WindowsCommon,
                                  'copy_vhd_disk')
        windows_common.WindowsCommon.copy_vhd_disk(self.fake_local_path(
            volume_cloned),self.fake_local_path(volume))

        mox.ReplayAll()

        drv.create_cloned_volume(volume, volume_cloned)

        mox.VerifyAll()