import base64
import cgi
import datetime
import email.utils
import io
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytz
from flask import Flask, Response, make_response, request
from requests import codes

from mock_vws._base64_decoding import decode_base64
from mock_vws._constants import ResultCodes, TargetStatuses
from mock_vws._database_matchers import get_database_matching_client_keys
from mock_vws._mock_common import json_dump, parse_multipart
from mock_vws.database import VuforiaDatabase

from ..vws._databases import get_all_databases
from mock_vws._query_validators import run_query_validators
from mock_vws._query_validators.exceptions import (
    DateHeaderNotGiven,
    DateFormatNotValid,
    RequestTimeTooSkewed,
    BadImage,
    AuthenticationFailure,
    AuthenticationFailureGoodFormatting,
    ImageNotGiven,
    AuthHeaderMissing,
    MalformedAuthHeader,
    UnknownParameters,
    InactiveProject,
    InvalidMaxNumResults,
    MaxNumResultsOutOfRange,
    InvalidIncludeTargetData,
    UnsupportedMediaType,
    InvalidAcceptHeader,
    BoundaryNotInBody,
    NoBoundaryFound,
    QueryOutOfBounds,
    ContentLengthHeaderTooLarge,
    ContentLengthHeaderNotInt
)

CLOUDRECO_FLASK_APP = Flask(__name__)


@CLOUDRECO_FLASK_APP.before_request
def validate_request() -> None:
    databases = get_all_databases()
    run_query_validators(
        request_headers=dict(request.headers),
        # TODO not sure about this one
        request_body=request.data,
        request_method=request.method,
        request_path=request.path,
        databases=databases,
    )


# @CLOUDRECO_FLASK_APP.errorhandler(DateHeaderNotGiven)
# def handle_date_header_not_given(e: DateHeaderNotGiven) -> Response:
#     content_type = 'text/plain; charset=ISO-8859-1'
#     response = make_response(e.response_text, e.status_code)
#     response.headers['Content-Type'] = content_type
#     response.headers['WWW-Authenticate'] = 'VWS'
#     assert isinstance(response, Response)
#     return response


@CLOUDRECO_FLASK_APP.after_request
def set_headers(response: Response) -> Response:
    response.headers['Connection'] = 'keep-alive'
    if response.status_code != codes.INTERNAL_SERVER_ERROR:
        response.headers['Content-Type'] = 'application/json'
    if response.status_code == codes.UNSUPPORTED_MEDIA_TYPE:
        # response.headers.pop('Content-Type')
        # TODO we need to remove this somehow but I don't know how
        response.headers['Content-Type'] = ''
    response.headers['Server'] = 'nginx'
    content_length = len(response.data)
    response.headers['Content-Length'] = str(content_length)
    date = email.utils.formatdate(None, localtime=False, usegmt=True)
    response.headers['Date'] = date
    return response


@CLOUDRECO_FLASK_APP.route('/v1/query', methods=['POST'])
def query() -> Tuple[str, int]:
    body_file = io.BytesIO(request.input_stream.getvalue())

    _, pdict = cgi.parse_header(request.headers['Content-Type'])
    parsed = parse_multipart(
        fp=body_file,
        pdict={
            'boundary': pdict['boundary'].encode(),
        },
    )

    [max_num_results] = parsed.get('max_num_results', ['1'])

    [include_target_data] = parsed.get('include_target_data', ['top'])
    include_target_data = include_target_data.lower()

    [image] = parsed['image']
    gmt = pytz.timezone('GMT')
    now = datetime.datetime.now(tz=gmt)

    processing_timedelta = datetime.timedelta(
        # TODO add this back
        # seconds=self._query_processes_deletion_seconds,
        seconds=0.2,
    )

    recognition_timedelta = datetime.timedelta(
        # TODO add this back
        # seconds=self._query_recognizes_deletion_seconds,
        seconds=0.2,
    )

    databases = get_all_databases()

    database = get_database_matching_client_keys(
        request_headers=dict(request.headers),
        request_body=request.input_stream.getvalue(),
        request_method=request.method,
        request_path=request.path,
        databases=databases,
    )

    assert isinstance(database, VuforiaDatabase)

    matching_targets = [
        target for target in database.targets
        if target.image.getvalue() == image
    ]

    not_deleted_matches = [
        target for target in matching_targets
        if target.active_flag and not target.delete_date
        and target.status == TargetStatuses.SUCCESS.value
    ]

    deletion_not_recognized_matches = [
        target for target in matching_targets
        if target.active_flag and target.delete_date and
        (now - target.delete_date) < recognition_timedelta
    ]

    matching_targets_with_processing_status = [
        target for target in matching_targets
        if target.status == TargetStatuses.PROCESSING.value
    ]

    active_matching_targets_delete_processing = [
        target for target in matching_targets
        if target.active_flag and target.delete_date and
        (now -
         target.delete_date) < (recognition_timedelta + processing_timedelta)
        and target not in deletion_not_recognized_matches
    ]

    if (
        matching_targets_with_processing_status
        or active_matching_targets_delete_processing
    ):
        # We return an example 500 response.
        # Each response given by Vuforia is different.
        #
        # Sometimes Vuforia will ignore matching targets with the
        # processing status, but we choose to:
        # * Do the most unexpected thing.
        # * Be consistent with every response.
        resources_dir = Path(__file__).parent / 'resources'
        filename = 'match_processing_response'
        match_processing_resp_file = resources_dir / filename
        cache_control = 'must-revalidate,no-cache,no-store'
        # TODO remove legacy
        # context.headers['Cache-Control'] = cache_control
        content_type = 'text/html; charset=ISO-8859-1'
        # TODO remove legacy
        # context.headers['Content-Type'] = content_type
        return (
            Path(match_processing_resp_file).read_text(),
            codes.INTERNAL_SERVER_ERROR,
            {
                'Cache-Control': cache_control,
                'Content-Type': content_type,
            },
        )

    matches = not_deleted_matches + deletion_not_recognized_matches

    results: List[Dict[str, Any]] = []
    for target in matches:
        target_timestamp = target.last_modified_date.timestamp()
        if target.application_metadata is None:
            application_metadata = None
        else:
            application_metadata = base64.b64encode(
                decode_base64(encoded_data=target.application_metadata),
            ).decode('ascii')
        target_data = {
            'target_timestamp': int(target_timestamp),
            'name': target.name,
            'application_metadata': application_metadata,
        }

        if include_target_data == 'all':
            result = {
                'target_id': target.target_id,
                'target_data': target_data,
            }
        elif include_target_data == 'top' and not results:
            result = {
                'target_id': target.target_id,
                'target_data': target_data,
            }
        else:
            result = {
                'target_id': target.target_id,
            }

        results.append(result)

    body = {
        'result_code': ResultCodes.SUCCESS.value,
        'results': results[:int(max_num_results)],
        'query_id': uuid.uuid4().hex,
    }

    value = json_dump(body)
    return value, codes.OK
