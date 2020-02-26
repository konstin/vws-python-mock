import base64
import datetime
import io
from typing import List, Tuple

import pytz
from flask import Flask, jsonify, request
from requests import codes

from mock_vws.database import VuforiaDatabase
from mock_vws.states import States
from mock_vws.target import Target

STORAGE_FLASK_APP = Flask(__name__)

VUFORIA_DATABASES: List[VuforiaDatabase] = []


@STORAGE_FLASK_APP.route('/reset', methods=['POST'])
def reset() -> Tuple[str, int]:
    # import pdb; pdb.set_trace()

    VUFORIA_DATABASES.clear()
    return '', codes.OK


@STORAGE_FLASK_APP.route('/databases', methods=['GET'])
def get_databases() -> Tuple[str, int]:
    databases = [database.to_dict() for database in VUFORIA_DATABASES]
    return jsonify(databases), codes.OK


@STORAGE_FLASK_APP.route('/databases', methods=['POST'])
def create_database() -> Tuple[str, int]:
    server_access_key = request.json['server_access_key']
    server_secret_key = request.json['server_secret_key']
    client_access_key = request.json['client_access_key']
    client_secret_key = request.json['client_secret_key']
    database_name = request.json['database_name']
    state = States(request.json['state_value'])

    database = VuforiaDatabase(
        server_access_key=server_access_key,
        server_secret_key=server_secret_key,
        client_access_key=client_access_key,
        client_secret_key=client_secret_key,
        database_name=database_name,
        state=state,
    )
    VUFORIA_DATABASES.append(database)
    return jsonify(database.to_dict()), codes.CREATED


@STORAGE_FLASK_APP.route(
    '/databases/<string:database_name>/targets',
    methods=['POST'],
)
def create_target(database_name: str) -> Tuple[str, int]:
    [database] = [
        database for database in VUFORIA_DATABASES
        if database.database_name == database_name
    ]
    image_base64 = request.json['image_base64']
    # import pdb; pdb.set_trace()
    image_bytes = base64.b64decode(image_base64)
    image = io.BytesIO(image_bytes)
    target = Target(
        name=request.json['name'],
        width=request.json['width'],
        image=image,
        active_flag=request.json['active_flag'],
        processing_time_seconds=request.json['processing_time_seconds'],
        application_metadata=request.json['application_metadata'],
    )
    # import pdb; pdb.set_trace()
    target.target_id = request.json['target_id']
    database.targets.append(target)
    # import pdb; pdb.set_trace(

    return jsonify(target.to_dict()), codes.CREATED


@STORAGE_FLASK_APP.route(
    '/databases/<string:database_name>/targets/<string:target_id>',
    methods=['DELETE'],
)
def delete_target(database_name: str, target_id: str) -> Tuple[str, int]:
    [database] = [
        database for database in VUFORIA_DATABASES
        if database.database_name == database_name
    ]
    [target] = [
        target for target in database.targets if target.target_id == target_id
    ]
    gmt = pytz.timezone('GMT')
    now = datetime.datetime.now(tz=gmt)
    target.delete_date = now
    return jsonify(target.to_dict()), codes.OK
