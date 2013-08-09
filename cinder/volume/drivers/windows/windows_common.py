# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Pedro Navarro Perez
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
Utility class for Windows Storage Server 2012 volume related operations.
"""

import os
import tempfile

from eventlet.green import subprocess
from oslo.config import cfg

from cinder import exception
from cinder.openstack.common import log as logging
from cinder.image import image_utils
from cinder.openstack.common import fileutils

# Check needed for unit testing on Unix
if os.name == 'nt':
    import wmi


LOG = logging.getLogger(__name__)

windows_opts = [
    cfg.StrOpt('qemu_img_cmd',
               default="qemu-img.exe",
               help='qemu-img is used to convert between '
                    'different image types'),
]

CONF = cfg.CONF
CONF.register_opts(windows_opts)


class WindowsCommon(object):
    """Executes volume driver commands on Windows Storage server."""

    def __init__(self, *args, **kwargs):
        #Set the flags
        self._conn_wmi = wmi.WMI(moniker='//./root/wmi')
        self._conn_cimv2 = wmi.WMI(moniker='//./root/cimv2')

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate.
        """
        #Invoking the portal an checking that is listening
        wt_portal = self._conn_wmi.WT_Portal()[0]
        listen = wt_portal.Listen
        if not listen:
            raise exception.VolumeBackendAPIException()

    def get_host_information(self, volume, target_name):
        #Getting the portal and port information
        wt_portal = self._conn_wmi.WT_Portal()[0]
        (address, port) = (wt_portal.Address, wt_portal.Port)
        #Getting the host information
        hosts = self._conn_wmi.WT_Host(Hostname=target_name)
        host = hosts[0]

        properties = {}
        properties['target_discovered'] = False
        properties['target_portal'] = '%s:%s' % (address, port)
        properties['target_iqn'] = host.TargetIQN
        properties['target_lun'] = 0
        properties['volume_id'] = volume['id']

        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()

            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

    def associate_initiator_with_iscsi_target(self, initiator_name, target_name):
        """Sets information used by the iSCSI target entry
        to identify the initiator associated with it"""
        cl = self._conn_wmi.__getattr__("WT_IDMethod")
        wt_idmethod = cl.new()
        wt_idmethod.HostName = target_name
        #Identification method is IQN
        wt_idmethod.Method = 4
        wt_idmethod.Value = initiator_name
        wt_idmethod.put()

    def delete_iscsi_target(self, initiator_name, target_name):
        """Desassigns target to initiators"""

        wt_idmethod = self._conn_wmi.WT_IDMethod(HostName=target_name,
                                                 Method=4,
                                                 Value=initiator_name)[0]
        wt_idmethod.Delete_()

    def create_volume(self, vhd_path, vol_name, vol_size):
        """ Creates a volume """
        cl = self._conn_wmi.__getattr__("WT_Disk")
        cl.NewWTDisk(DevicePath=vhd_path,
                     Description=vol_name,
                     SizeInMB=vol_size * 1024)

    def delete_volume(self, vol_name, vhd_path):
        """Driver entry point for destroying existing volumes."""
        wt_disk = self._conn_wmi.WT_Disk(Description=vol_name)[0]
        wt_disk.Delete_()
        vhdfiles = self._conn_cimv2.query(
            "Select * from CIM_DataFile where Name = '" +
            vhd_path + "'")
        if len(vhdfiles) > 0:
            vhdfiles[0].Delete()

    def create_snapshot(self, vol_name, snapshot_name):
        """Driver entry point for creating a snapshot.
        """
        wt_disk = self._conn_wmi.WT_Disk(Description=vol_name)[0]
        #API Calls gets Generic Failure
        cl = self._conn_wmi.__getattr__("WT_Snapshot")
        disk_id = wt_disk.WTD
        out = cl.Create(WTD=disk_id)
        #Setting description since it used as a KEY
        wt_snapshot_created = self._conn_wmi.WT_Snapshot(Id=out[0])[0]
        wt_snapshot_created.Description = snapshot_name
        wt_snapshot_created.put()

    def create_volume_from_snapshot(self, vol_name, snapshot_name):
        """Driver entry point for exporting snapshots as volumes."""
        wt_snapshot = self._conn_wmi.WT_Snapshot(Description=snapshot_name)[0]
        disk_id = wt_snapshot.Export()[0]
        wt_disk = self._conn_wmi.WT_Disk(WTD=disk_id)[0]
        wt_disk.Description = vol_name
        wt_disk.put()

    def delete_snapshot(self, snapshot_name):
        """Driver entry point for deleting a snapshot."""
        wt_snapshot = self._conn_wmi.WT_Snapshot(Description=snapshot_name)[0]
        wt_snapshot.Delete_()

    def create_iscsi_target(self, target_name, ensure):
        #ISCSI target creation
        try:
            cl = self._conn_wmi.__getattr__("WT_Host")
            cl.NewHost(HostName=target_name)
        except Exception as exc:
            excep_info = exc.com_error.excepinfo[2]
            if not ensure or excep_info.find(u'The file exists') == -1:
                raise
            else:
                LOG.info(_('Ignored target creation error "%s"'
                           ' while ensuring export'), exc)

    def remove_iscsi_target(self, target_name):
        #Get ISCSI target
        wt_host = self._conn_wmi.WT_Host(HostName=target_name)[0]
        wt_host.RemoveAllWTDisks()
        wt_host.Delete_()

    def add_disk_to_target(self, vol_name, target_name):
        """ Adds the disk to the target """
        q = self._conn_wmi.WT_Disk(Description=vol_name)
        if not len(q):
            LOG.debug(_('Disk not found: %s'), vol_name)
            return None
        wt_disk = q[0]
        wt_host = self._conn_wmi.WT_Host(HostName=target_name)[0]
        wt_host.AddWTDisk(wt_disk.WTD)

    def convert_image(self, source, dest, out_format):
        """Convert image to other format"""
        cmd = (CONF.qemu_img_cmd, 'convert', '-O', out_format, source, dest)
        self._execute(*cmd)

    def qemu_img_info(self, path):
        """Return a object containing the parsed output from qemu-img info."""
        out, err = self._execute(CONF.qemu_img_cmd, 'info', path)
        return image_utils.QemuImgInfo(out)

    def fetch_to_vhd(self, context, image_service,
                 image_id, dest,
                 user_id=None, project_id=None):
        if (CONF.image_conversion_dir and not
                os.path.exists(CONF.image_conversion_dir)):
            os.makedirs(CONF.image_conversion_dir)

        with image_utils.temporary_file() as tmp:
            LOG.debug("Downloading image %s was to tmp dest: " ,image_id)
            image_utils.fetch(context, image_service, image_id, tmp, user_id,
                              project_id)

            LOG.debug("Downloading DONE %s was to tmp dest: " ,image_id)

            data = self.qemu_img_info(tmp)
            fmt = data.file_format
            if fmt is None:
                raise exception.ImageUnacceptable(
                    reason=_("'qemu-img info' parsing failed."),
                    image_id=image_id)

            backing_file = data.backing_file
            if backing_file is not None:
                raise exception.ImageUnacceptable(
                    image_id=image_id,
                    reason=_("fmt=%(fmt)s backed by:"
                             "%(backing_file)s") % {
                                 'fmt': fmt,
                                 'backing_file': backing_file,
                             })

            if 'vpc' not in fmt:
                self.convert_image(tmp, dest, 'vpc')
            else:
                self.copy_vhd_disk(tmp, dest)

            data = self.qemu_img_info(dest)
            if data.file_format != "vpc":
                raise exception.ImageUnacceptable(
                    image_id=image_id,
                    reason=_("Converted to vhd, but format is now %s") %
                    data.file_format)

    def upload_volume(self, context, image_service, image_meta, volume_path):
        LOG.debug("Uploading volume %s: " ,volume_path)
        image_id = image_meta['id']
        if (image_meta['disk_format'] == 'vhd'):
            LOG.debug("%s was raw, no need to convert to %s" %
                      (image_id, image_meta['disk_format']))
            with fileutils.file_open(volume_path) as image_file:
                image_service.update(context, image_id, {}, image_file)
            return

        if (CONF.image_conversion_dir and not
                os.path.exists(CONF.image_conversion_dir)):
            os.makedirs(CONF.image_conversion_dir)

        #Copy the volume to the image conversion dir
        temp_vhd_path = os.path.join(CONF.image_conversion_dir, str(image_meta['id']) + ".vhd")
        self.copy_vhd_disk(volume_path, temp_vhd_path)

        fd, tmp = tempfile.mkstemp(dir=CONF.image_conversion_dir)
        os.close(fd)
        with fileutils.remove_path_on_error(tmp):
            LOG.debug("%s was vhd, converting to %s" %
                      (image_id, image_meta['disk_format']))
            self.convert_image(temp_vhd_path, tmp, image_meta['disk_format'])

            data = self.qemu_img_info(tmp)
            if data.file_format != image_meta['disk_format']:
                raise exception.ImageUnacceptable(
                    image_id=image_id,
                    reason=_("Converted to %(f1)s, but format is now %(f2)s") %
                    {'f1': image_meta['disk_format'], 'f2': data.file_format})

            LOG.debug("Converted size of %s is: %s", data.backing_file, data.disk_size)

            with fileutils.file_open(tmp) as image_file:
                image_service.update(context, image_id, image_meta, image_file)
            os.unlink(tmp)

    def copy_vhd_disk(self, source_path, destination_path):
        """ Copies the vhd disk from source path to destination path """
        vhdfiles = self._conn_cimv2.query(
            "Select * from CIM_DataFile where Name = '" +
            source_path + "'")
        if len(vhdfiles) > 0:
            vhdfiles[0].Copy(destination_path)

    def extend(self, vol_name, additional_size):
        """Extend an Existing Volume."""
        q = self._conn_wmi.WT_Disk(Description=vol_name)
        if not len(q):
            LOG.debug(_('Disk not found: %s'), vol_name)
            return None
        wt_disk = q[0]
        wt_disk.Extend(additional_size)

    def _execute(self, *cmd, **kwargs):
        _PIPE = subprocess.PIPE  # pylint: disable=E1101
        proc = subprocess.Popen(
            cmd,
            stdin=_PIPE,
            stdout=_PIPE,
            stderr=_PIPE,
        )
        stdout_value, stderr_value = proc.communicate()
        return stdout_value, stderr_value