from flask import request
from flask_restplus import Resource, Namespace, fields
from flask_jwt_extended import jwt_required

from cnaas_nms.db.device import Device, DeviceType
from cnaas_nms.db.session import sqla_session
from cnaas_nms.db.settings import VerifyPathException, get_settings
from cnaas_nms.api.generic import empty_result
from cnaas_nms.version import __api_version__


api = Namespace('settings', description='Settings',
                prefix='/api/{}'.format(__api_version__))

settings_model = api.model('settings', {
    'hostname': fields.String(required=True),
    'device_type': fields.String(required=True),
})


class SettingsApi(Resource):
    @jwt_required
    @api.expect(settings_model)
    def get(self):
        """ Get settings """
        json_data = request.get_json()
        hostname = None
        device_type = None
        if 'hostname' in json_data:
            if Device.valid_hostname(json_data['hostname']):
                hostname = json_data['hostname']
            else:
                return empty_result('error', "Invalid hostname specified"), 400
            with sqla_session() as session:
                dev: Device = session.query(Device).\
                    filter(Device.hostname == hostname).one_or_none()
                if dev:
                    device_type = dev.device_type
                else:
                    return empty_result('error', "Hostname not found in database"), 400
        if 'device_type' in json_data:
            if DeviceType.has_name(json_data['device_type'].upper()):
                device_type = DeviceType[json_data['device_type'].upper()]
            else:
                return empty_result('error', "Invalid device type specified"), 400

        try:
            settings, settings_origin = get_settings(hostname, device_type)
        except Exception as e:
            return empty_result('error', "Error getting settings: {}".format(str(e))), 400

        return empty_result(data={'settings': settings, 'settings_origin': settings_origin})


api.add_resource(SettingsApi, '')
