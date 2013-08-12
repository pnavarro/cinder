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
Volume driver for Windows Server 2012

This driver requires ISCSI target role installed

"""

import os

from oslo.config import cfg

from cinder import exception
from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume.drivers.windows import windows_common

# Check needed for unit testing on Unix
if os.name == 'nt':
    import wmi

VERSION = '1.0'
LOG = logging.getLogger(__name__)

windows_opts = [
    cfg.StrOpt('windows_iscsi_lun_path',
               default='C:\iSCSIVirtualDisks',
               help='Path to store VHD backed volumes'),
]

CONF = cfg.CONF
CONF.register_opts(windows_opts)


class WindowsDriver(driver.ISCSIDriver):
    """Executes volume driver commands on Windows Storage server."""

    def __init__(self, *args, **kwargs):
        super(WindowsDriver, self).__init__(*args, **kwargs)
        self.common = windows_common.WindowsCommon()

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate.
        """
        self.common.check_for_setup_error()

    def initialize_connection(self, volume, connector):
        """Driver entry point to attach a volume to an instance.
        """
        initiator_name = connector['initiator']
        target_name = volume['provider_location']

        self.common.associate_initiator_with_iscsi_target(target_name,
                                                          initiator_name)

        properties = self.common.get_host_information(volume, target_name)

        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to unattach a volume from an instance.

        Unmask the LUN on the storage system so the given initiator can no
        longer access it.
        """
        initiator_name = connector['initiator']
        target_name = volume['provider_location']
        self.common.delete_iscsi_target(initiator_name, target_name)

    def create_volume(self, volume):
        """Driver entry point for creating a new volume."""
        vhd_path = self.local_path(volume)
        vol_name = volume['name']
        vol_size = volume['size']

        self.common.create_volume(vhd_path, vol_name, vol_size)

    def local_path(self, volume):
        base_vhd_folder = CONF.windows_iscsi_lun_path
        if not os.path.exists(base_vhd_folder):
            LOG.debug(_('Creating folder %s '), base_vhd_folder)
            os.makedirs(base_vhd_folder)
        return os.path.join(base_vhd_folder, str(volume['name']) + ".vhd")

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        vol_name = volume['name']
        vhd_path = self.local_path(volume)

        self.common.delete_volume(vol_name, vhd_path)

    def create_snapshot(self, snapshot):
        """Driver entry point for creating a snapshot.
        """
        #Getting WT_Snapshot class
        vol_name = snapshot['volume_name']
        snapshot_name = snapshot['name']

        self.common.create_snapshot(vol_name, snapshot_name)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Driver entry point for exporting snapshots as volumes."""
        snapshot_name = snapshot['name']
        vol_name = volume['name']
        self.common.create_volume_from_snapshot(vol_name, snapshot_name)

    def delete_snapshot(self, snapshot):
        """Driver entry point for deleting a snapshot."""
        snapshot_name = snapshot['name']
        self.common.delete_snapshot(snapshot_name)

    def _do_export(self, _ctx, volume, ensure=False):
        """Do all steps to get disk exported as LUN 0 at separate target.

        :param volume: reference of volume to be exported
        :param ensure: if True, ignore errors caused by already existing
            resources
        :return: iscsiadm-formatted provider location string
        """
        target_name = "%s%s" % (CONF.iscsi_target_prefix, volume['name'])
        self.common.create_iscsi_target(target_name, ensure)

        #Get the disk to add
        vol_name = volume['name']
        self.common.add_disk_to_target(vol_name, target_name)

        return target_name

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        self._do_export(context, volume, ensure=True)

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        loc = self._do_export(context, volume, ensure=False)
        return {'provider_location': loc}

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume.
        """
        target_name = "%s%s" % (CONF.iscsi_target_prefix, volume['name'])

        self.common.remove_iscsi_target(target_name)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        #Convert to VHD and file back to VHD
        self.common.fetch_to_vhd(context, image_service, image_id,
                                 self.local_path(volume))

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        #Convert to image destination
        self.common.upload_volume(context,
                                  image_service,
                                  image_meta,
                                  self.local_path(volume))

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        #Create a new volume
        #Copy VHD file of the volume to clone to the created volume
        self.create_volume(volume)
        self.common.copy_vhd_disk(self.local_path(src_vref),
                                  self.local_path(volume))

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info for Windows device."""

        LOG.debug(_("Updating volume stats"))
        data = {}
        backend_name = self.__class__.__name__
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or self.__class__.__name__
        data["vendor_name"] = 'Microsoft'
        data["driver_version"] = VERSION
        data["storage_protocol"] = 'iSCSI'
        data['total_capacity_gb'] = 'infinite'
        data['free_capacity_gb'] = 'infinite'
        data['reserved_percentage'] = 100
        data['QoS_support'] = False
        self._stats = data

    def extend_volume(self, volume, new_size):
        """Extend an Existing Volume."""
        old_size = volume['size']
        additional_size = (new_size - old_size) * 1024
        try:
            self.common.extend(volume['name'], additional_size)
        except Exception:
            msg = _('Failed to Extend Volume '
                    '%(volname)s') % {'volname': volume['name']}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug(_("Extend volume from %(old_size) to %(new_size)"),
                  {'old_size': old_size, 'new_size': new_size})