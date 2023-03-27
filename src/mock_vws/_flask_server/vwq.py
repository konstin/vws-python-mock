"""
A fake implementation of the Vuforia Web Query API using Flask.

See
https://library.vuforia.com/web-api/vuforia-query-web-api
"""

import email.utils
from enum import StrEnum, auto
from http import HTTPStatus

import requests
from flask import Flask, Response, request
from pydantic import BaseSettings
from werkzeug.datastructures import Headers

from mock_vws._query_tools import (
    ActiveMatchingTargetsDeleteProcessing,
    get_query_match_response_text,
)
from mock_vws._query_validators import run_query_validators
from mock_vws._query_validators.exceptions import (
    DeletedTargetMatched,
    ValidatorException,
)
from mock_vws.database import VuforiaDatabase
from mock_vws.image_matchers import (
    AverageHashMatcher,
    ExactMatcher,
    ImageMatcher,
)
from mock_vws.target_raters import (
    BrisqueTargetTrackingRater,
    RandomTargetTrackingRater,
    TargetTrackingRater,
)

CLOUDRECO_FLASK_APP = Flask(import_name=__name__)
CLOUDRECO_FLASK_APP.config["PROPAGATE_EXCEPTIONS"] = True


class _ImageMatcherChoice(StrEnum):
    """Image matcher choices."""

    EXACT = auto()
    AVERAGE_HASH = auto()

    def to_image_matcher(self) -> ImageMatcher:
        """Get the image matcher."""
        matcher = {
            _ImageMatcherChoice.EXACT: ExactMatcher(),
            _ImageMatcherChoice.AVERAGE_HASH: AverageHashMatcher(threshold=10),
        }[self]
        assert isinstance(matcher, ImageMatcher)
        return matcher


class _TargetRaterChoice(StrEnum):
    """Target rater choices."""

    RANDOM = auto()
    BRISQUE = auto()

    def to_target_rater(self) -> TargetTrackingRater:
        """Get the target rater."""
        rater = {
            _TargetRaterChoice.RANDOM: RandomTargetTrackingRater(),
            _TargetRaterChoice.BRISQUE: BrisqueTargetTrackingRater(),
        }[self]
        assert isinstance(rater, TargetTrackingRater)
        return rater


class VWQSettings(BaseSettings):
    """Settings for the VWQ Flask app."""

    vwq_host: str = ""
    target_manager_base_url: str
    deletion_processing_seconds: float = 3.0
    deletion_recognition_seconds: float = 0.2
    query_image_matcher: _ImageMatcherChoice = _ImageMatcherChoice.AVERAGE_HASH
    target_rater: _TargetRaterChoice = _TargetRaterChoice.BRISQUE


def get_all_databases() -> set[VuforiaDatabase]:
    """
    Get all database objects from the target manager back-end.
    """
    settings = VWQSettings.parse_obj(obj={})
    response = requests.get(
        url=f"{settings.target_manager_base_url}/databases",
        timeout=30,
    )
    target_tracking_rater = settings.target_rater.to_target_rater()
    return {
        VuforiaDatabase.from_dict(
            database_dict=database_dict,
            target_tracking_rater=target_tracking_rater,
        )
        for database_dict in response.json()
    }


@CLOUDRECO_FLASK_APP.before_request
def set_terminate_wsgi_input() -> None:
    """
    We set ``wsgi.input_terminated`` to ``True`` when going through
    ``requests``, so that requests have the given ``Content-Length`` headers
    and the given data in ``request.headers`` and ``request.data``.

    We set this to ``False`` when running an application as standalone.
    This is because when running the Flask application, if this is set,
    reading ``request.data`` hangs.

    Therefore, when running the real Flask application, the behavior is not the
    same as the real Vuforia.
    This is documented as a difference in the documentation for this package.
    """
    terminate_wsgi_input = CLOUDRECO_FLASK_APP.config.get(
        "TERMINATE_WSGI_INPUT",
        False,
    )
    request.environ["wsgi.input_terminated"] = terminate_wsgi_input


@CLOUDRECO_FLASK_APP.errorhandler(ValidatorException)
def handle_exceptions(exc: ValidatorException) -> Response:
    """
    Return the error response associated with the given exception.
    """
    response = Response(
        status=exc.status_code.value,
        response=exc.response_text,
        headers=exc.headers,
    )

    response.headers = Headers(exc.headers)
    return response


@CLOUDRECO_FLASK_APP.route("/v1/query", methods=["POST"])
def query() -> Response:
    """
    Perform an image recognition query.
    """
    settings = VWQSettings.parse_obj(obj={})
    query_match_checker = settings.query_image_matcher.to_image_matcher()

    databases = get_all_databases()
    request_body = request.stream.read()
    run_query_validators(
        request_headers=dict(request.headers),
        request_body=request_body,
        request_method=request.method,
        request_path=request.path,
        databases=databases,
    )
    date = email.utils.formatdate(None, localtime=False, usegmt=True)

    try:
        response_text = get_query_match_response_text(
            request_headers=dict(request.headers),
            request_body=request_body,
            request_method=request.method,
            request_path=request.path,
            databases=databases,
            query_processes_deletion_seconds=settings.deletion_processing_seconds,
            query_recognizes_deletion_seconds=(
                settings.deletion_recognition_seconds
            ),
            query_match_checker=query_match_checker,
        )
    except ActiveMatchingTargetsDeleteProcessing as exc:
        raise DeletedTargetMatched from exc

    headers = {
        "Content-Type": "application/json",
        "Date": date,
        "Connection": "keep-alive",
        "Server": "nginx",
    }
    return Response(
        status=HTTPStatus.OK,
        response=response_text,
        headers=headers,
    )


if __name__ == "__main__":  # pragma: no cover
    SETTINGS = VWQSettings.parse_obj(obj={})
    CLOUDRECO_FLASK_APP.run(debug=True, host=SETTINGS.vwq_host)
