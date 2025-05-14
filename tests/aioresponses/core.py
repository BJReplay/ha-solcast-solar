"""Core aioresponses.

This module is a modified version of the original aioresponses project.
The original by P. Nuckowski may be found at https://github.com/pnuckowski/aioresponses

It has been modernised, and modified to avoid being used as a context manager.
"""

import asyncio
from collections.abc import Callable
import copy
from functools import wraps
import inspect
import json
from re import Pattern
from typing import Any, NamedTuple, Optional, TypeVar, cast
from unittest.mock import Mock, patch
from urllib.parse import parse_qsl, urlencode
from uuid import uuid4

from aiohttp import (
    ClientConnectionError,
    ClientResponse,
    ClientSession,
    RequestInfo,
    StreamReader,
    hdrs,
    http,
)
from aiohttp.client_proto import ResponseHandler
from aiohttp.helpers import TimerNoop
from multidict import CIMultiDict, CIMultiDictProxy, MultiDict
from yarl import URL

_FuncT = TypeVar("_FuncT", bound=Callable[..., Any])


def stream_reader_factory(
    loop: asyncio.AbstractEventLoop | None = None,
) -> StreamReader:
    """Create a StreamReader instance."""
    protocol = ResponseHandler(loop=loop)
    return StreamReader(protocol, limit=2**16, loop=loop)


def merge_params(url: URL | str, params: dict | None = None) -> "URL":
    """Merge URL and params."""
    url = URL(url)
    if params:
        query_params = MultiDict(url.query)
        query_params.extend(url.with_query(params).query)
        return url.with_query(query_params)
    return url


def normalize_url(url: URL | str) -> "URL":
    """Normalize URL to make comparisons."""
    url = URL(url)
    return url.with_query(urlencode(sorted(parse_qsl(url.query_string))))


class CallbackResult:
    """The result that must be returned by a callback function."""

    def __init__(
        self,
        method: str = hdrs.METH_GET,
        status: int = 200,
        body: str | bytes = "",
        content_type: str = "application/json",
        payload: dict | None = None,
        headers: dict | None = None,
        response_class: type[ClientResponse] | None = None,
        reason: str | None = None,
    ) -> None:
        """Initialize the callback result."""
        self.method = method
        self.status = status
        self.body = body
        self.content_type = content_type
        self.payload = payload
        self.headers = headers
        self.response_class = response_class
        self.reason = reason


class RequestMatch:
    """Execute a request based on the URL and method."""

    url_or_pattern: URL | Pattern = None

    def __init__(
        self,
        url: URL | str | Pattern,
        method: str = hdrs.METH_GET,
        status: int = 200,
        body: str | bytes = "",
        payload: dict | None = None,
        exception: Exception | None = None,
        headers: dict | None = None,
        content_type: str = "application/json",
        response_class: type[ClientResponse] | None = None,
        timeout: bool = False,
        repeat: bool | int = False,
        reason: str | None = None,
        callback: Callable | None = None,
    ) -> None:
        """Initialize the request match."""
        if isinstance(url, Pattern):
            self.url_or_pattern = url
            self.match_func = self.match_regexp
        else:
            self.url_or_pattern = normalize_url(url)
            self.match_func = self.match_str
        self.method = method.lower()
        self.status = status
        self.body = body
        self.payload = payload
        self.exception = exception
        if timeout:
            self.exception = TimeoutError("Connection timeout test")
        self.headers = headers
        self.content_type = content_type
        self.response_class = response_class
        self.repeat = repeat
        self.reason = reason
        if self.reason is None:
            try:
                self.reason = http.RESPONSES[self.status][0]
            except (IndexError, KeyError):
                self.reason = ""
        self.callback = callback

    def match_str(self, url: URL) -> bool:
        """Match the URL as a string."""
        return self.url_or_pattern == url

    def match_regexp(self, url: URL) -> bool:
        """Match the URL as a regular expression."""
        return bool(self.url_or_pattern.match(str(url)))

    def match(self, method: str, url: URL) -> bool:
        """Match the request based on the URL and method."""
        if self.method != method.lower():
            return False
        return self.match_func(url)

    def _build_raw_headers(self, headers: dict) -> tuple:
        """Convert a dict of headers to a tuple of tuples. Mimics the format of ClientResponse."""
        raw_headers = []
        for k, v in headers.items():
            raw_headers.append((k.encode("utf8"), v.encode("utf8")))
        return tuple(raw_headers)

    def _build_response(
        self,
        url: URL | str,
        method: str = hdrs.METH_GET,
        request_headers: dict | None = None,
        status: int = 200,
        body: str | bytes = "",
        content_type: str = "application/json",
        payload: dict | None = None,
        headers: dict | None = None,
        response_class: type[ClientResponse] | None = None,
        reason: str | None = None,
    ) -> ClientResponse:
        if response_class is None:
            response_class = ClientResponse
        if payload is not None:
            body = json.dumps(payload)
        if not isinstance(body, bytes):
            body = str.encode(body)
        if request_headers is None:
            request_headers = {}
        loop = Mock()
        loop.get_debug = Mock()
        loop.get_debug.return_value = True
        kwargs: dict[str, Any] = {}
        kwargs["request_info"] = RequestInfo(url=url, method=method, headers=CIMultiDictProxy(CIMultiDict(**request_headers)), real_url=url)
        kwargs["writer"] = None
        kwargs["continue100"] = None
        kwargs["timer"] = TimerNoop()
        kwargs["traces"] = []
        kwargs["loop"] = loop
        kwargs["session"] = None

        # We need to initialize headers manually
        _headers = CIMultiDict({hdrs.CONTENT_TYPE: content_type})
        if headers:
            _headers.update(headers)
        raw_headers = self._build_raw_headers(_headers)
        resp = response_class(method, url, **kwargs)

        for hdr in _headers.getall(hdrs.SET_COOKIE, ()):
            resp.cookies.load(hdr)

        # Reified attributes
        resp._headers = _headers
        resp._raw_headers = raw_headers

        resp.status = status
        resp.reason = reason
        resp.content = stream_reader_factory(loop)
        resp.content.feed_data(body)
        resp.content.feed_eof()
        return resp

    async def build_response(self, url: URL, **kwargs: Any) -> ClientResponse | Exception:
        """Build the response."""
        if callable(self.callback):
            if asyncio.iscoroutinefunction(self.callback):
                result = await self.callback(url, **kwargs)
            else:
                result = self.callback(url, **kwargs)
        else:
            result = None

        if self.exception is not None:
            return self.exception

        result = self if result is None else result
        return self._build_response(
            url=url,
            method=result.method,
            request_headers=kwargs.get("headers"),
            status=result.status,
            body=result.body,
            content_type=result.content_type,
            payload=result.payload,
            headers=result.headers,
            response_class=result.response_class,
            reason=result.reason,
        )

    def __repr__(self) -> str:
        """Return the string representation of the request match."""
        return f"RequestMatch('{self.url_or_pattern}')"


class RequestCall(NamedTuple):
    """Named tuple for the request call."""

    args: tuple
    kwargs: dict


class aioresponses:
    """Mock aiohttp requests made by ClientSession."""

    _matches: str | RequestMatch = None
    _responses: list[ClientResponse] = None
    requests: dict = None

    def __init__(self, **kwargs: Any) -> None:
        """Initialize aioresponses."""
        self._param = kwargs.pop("param", None)
        self._passthrough = kwargs.pop("passthrough", [])
        self.passthrough_unmatched = kwargs.pop("passthrough_unmatched", False)
        self.patcher = patch("aiohttp.client.ClientSession._request", side_effect=self._request_mock, autospec=True)

        self.requests = {}

        self.start()

    def __call__(self, f: _FuncT) -> _FuncT:
        """Class __call__. Allows for use as a decorator."""

        def _pack_arguments(ctx, *args, **kwargs) -> tuple[tuple, dict]:
            if self._param:
                kwargs[self._param] = ctx
            else:
                args += (ctx,)
            return args, kwargs

        if asyncio.iscoroutinefunction(f):

            @wraps(f)
            async def wrapped(*args, **kwargs):
                with self as ctx:
                    args, kwargs = _pack_arguments(ctx, *args, **kwargs)
                    return await f(*args, **kwargs)
        else:

            @wraps(f)
            def wrapped(*args, **kwargs):
                with self as ctx:
                    args, kwargs = _pack_arguments(ctx, *args, **kwargs)
                    return f(*args, **kwargs)

        return cast(_FuncT, wrapped)

    def clear(self) -> None:
        """Clear all the responses and matches."""
        self._responses.clear()
        self._matches.clear()

    def start(self) -> None:
        """Patch aiohttp."""
        self._responses = []
        self._matches = {}
        self.patcher.start()
        self.patcher.return_value = self._request_mock

    def stop(self) -> None:
        """Stop patching aiohttp."""
        for response in self._responses:
            response.close()
        self.patcher.stop()
        self.clear()

    def head(self, url: URL | str | Pattern, **kwargs: Any) -> None:
        """Add a HEAD request."""
        self.add(url, method=hdrs.METH_HEAD, **kwargs)

    def get(self, url: URL | str | Pattern, **kwargs: Any) -> None:
        """Add a GET request."""
        self.add(url, method=hdrs.METH_GET, **kwargs)

    def post(self, url: URL | str | Pattern, **kwargs: Any) -> None:
        """Add a POST request."""
        self.add(url, method=hdrs.METH_POST, **kwargs)

    def put(self, url: URL | str | Pattern, **kwargs: Any) -> None:
        """Add a PUT request."""
        self.add(url, method=hdrs.METH_PUT, **kwargs)

    def patch(self, url: URL | str | Pattern, **kwargs: Any) -> None:
        """Add a PATCH request."""
        self.add(url, method=hdrs.METH_PATCH, **kwargs)

    def delete(self, url: URL | str | Pattern, **kwargs: Any) -> None:
        """Add a DELETE request."""
        self.add(url, method=hdrs.METH_DELETE, **kwargs)

    def options(self, url: URL | str | Pattern, **kwargs: Any) -> None:
        """Add an OPTIONS request."""
        self.add(url, method=hdrs.METH_OPTIONS, **kwargs)

    def add(
        self,
        url: URL | str | Pattern,
        method: str = hdrs.METH_GET,
        status: int = 200,
        body: str | bytes = "",
        exception: Exception | None = None,
        content_type: str = "application/json",
        payload: dict | None = None,
        headers: dict | None = None,
        response_class: type[ClientResponse] | None = None,
        repeat: bool | int = False,
        timeout: bool = False,
        reason: str | None = None,
        callback: Callable | None = None,
    ) -> None:
        """Add a request."""
        self._matches[str(uuid4())] = RequestMatch(
            url,
            method=method,
            status=status,
            content_type=content_type,
            body=body,
            exception=exception,
            payload=payload,
            headers=headers,
            response_class=response_class,
            repeat=repeat,
            timeout=timeout,
            reason=reason,
            callback=callback,
        )

    def change_url(self, url: URL | str | Pattern, new_url: URL | str | Pattern) -> None:
        """Change a request url."""

        for key, matcher in self._matches.items():
            if isinstance(url, Pattern):
                if matcher.url_or_pattern == url:
                    if isinstance(new_url, Pattern):
                        matcher.url_or_pattern = new_url
                        matcher.match_func = matcher.match_regexp
                        break
                    else:
                        matcher.url_or_pattern = normalize_url(new_url)
                        matcher.match_func = matcher.match_str
                        break
            else:
                if matcher.url_or_pattern == normalize_url(url):
                    if isinstance(new_url, Pattern):
                        matcher.url_or_pattern = new_url
                        matcher.match_func = matcher.match_regexp
                        break
                    else:
                        matcher.url_or_pattern = normalize_url(new_url)
                        matcher.match_func = matcher.match_str
                        break

    def _format_call_signature(self, *args, **kwargs) -> str:
        message = "%s(%%s)" % self.__class__.__name__ or "mock"  # noqa: UP031
        formatted_args = ""
        args_string = ", ".join([repr(arg) for arg in args])
        kwargs_string = ", ".join([f"{key}={value!r}" for key, value in kwargs.items()])
        if args_string:
            formatted_args = args_string
        if kwargs_string:
            if formatted_args:
                formatted_args += ", "
            formatted_args += kwargs_string

        return message % formatted_args

    def assert_not_called(self):
        """Assert that the mock was never called."""
        if len(self.requests) != 0:
            msg = f"Expected '{self.__class__.__name__}' to not have been called. Called {len(self._responses)} times."
            raise AssertionError(msg)

    def assert_called(self):
        """Assert that the mock was called at least once."""
        if len(self.requests) == 0:
            msg = f"Expected '{self.__class__.__name__}' to have been called."
            raise AssertionError(msg)

    def assert_called_once(self):
        """Assert that the mock was called only once."""
        call_count = len(self.requests)
        if call_count == 1:
            call_count = len(list(self.requests.values())[0])
        if call_count != 1:
            msg = f"Expected '{self.__class__.__name__}' to have been called once. Called {call_count} times."

            raise AssertionError(msg)

    def assert_called_with(self, url: URL | str | Pattern, method: str = hdrs.METH_GET, *args: Any, **kwargs: Any):
        """Assert that the last call was made with the specified arguments.

        Raises an AssertionError if the args and keyword args passed in are
        different to the last call to the mock.
        """
        url = normalize_url(merge_params(url, kwargs.get("params")))
        method = method.upper()
        key = (method, url)
        try:
            expected = self.requests[key][-1]
        except KeyError:
            expected_string = self._format_call_signature(url, method=method, *args, **kwargs)  # noqa: B026
            raise AssertionError(f"{expected_string} call not found")
        actual = self._build_request_call(method, *args, **kwargs)
        if expected != actual:
            raise AssertionError(f"{self._format_call_signature(expected)} != {self._format_call_signature(actual)}")

    def assert_any_call(self, url: URL | str | Pattern, method: str = hdrs.METH_GET, *args: Any, **kwargs: Any):
        """Assert the mock has been called with the specified arguments.

        The assert passes if the mock has *ever* been called, unlike
        `assert_called_with` and `assert_called_once_with` that only pass if
        the call is the most recent one.
        """
        url = normalize_url(merge_params(url, kwargs.get("params")))
        method = method.upper()
        key = (method, url)

        try:
            self.requests[key]
        except KeyError:
            raise AssertionError(f"{self._format_call_signature(url, method=method, *args, **kwargs)} call not found")  # noqa: B026

    def assert_called_once_with(self, *args: Any, **kwargs: Any):
        """Assert that the mock was called once with the specified arguments.

        Raises an AssertionError if the args and keyword args passed in are
        different to the only call to the mock.
        """
        self.assert_called_once()
        self.assert_called_with(*args, **kwargs)

    @staticmethod
    def is_exception(resp_or_exc: ClientResponse | Exception) -> bool:
        """Check if the response is an exception."""
        if inspect.isclass(resp_or_exc):
            parent_classes = set(inspect.getmro(resp_or_exc))
            if {Exception, BaseException} & parent_classes:
                return True
        elif isinstance(resp_or_exc, (Exception, BaseException)):
            return True
        return False

    async def match(self, method: str, url: URL, allow_redirects: bool = True, **kwargs: Any) -> Optional["ClientResponse"]:
        """Match the request."""
        history = []
        while True:
            for key, matcher in self._matches.items():  # noqa: B007
                if matcher.match(method, url):
                    response_or_exc = await matcher.build_response(url, allow_redirects=allow_redirects, **kwargs)
                    break
            else:
                return None

            if isinstance(matcher.repeat, bool):
                if not matcher.repeat:
                    del self._matches[key]
            else:
                if matcher.repeat == 1:
                    del self._matches[key]
                matcher.repeat -= 1

            if self.is_exception(response_or_exc):
                raise response_or_exc
            # If response_or_exc was an exception, it would have been raised.
            # At this point we can be sure it's a ClientResponse
            response: ClientResponse = response_or_exc
            is_redirect = response.status in (301, 302, 303, 307, 308)
            if is_redirect and allow_redirects:
                if hdrs.LOCATION not in response.headers:
                    break
                history.append(response)
                redirect_url = URL(response.headers[hdrs.LOCATION])
                if redirect_url.is_absolute():
                    url = redirect_url
                else:
                    url = url.join(redirect_url)
                method = "get"
                continue
            else:  # noqa: RET507
                break

        response._history = tuple(history)
        return response

    async def _request_mock(self, orig_self: ClientSession, method: str, url: URL | str, *args: tuple, **kwargs: Any) -> "ClientResponse":
        """Return mocked response object or raise connection error."""
        if orig_self.closed:
            raise RuntimeError("Session is closed")

        # Join url with ClientSession._base_url
        url = orig_self._build_url(url)
        url_origin = str(url)
        # Combine ClientSession headers with passed headers
        if orig_self.headers:
            kwargs["headers"] = orig_self._prepare_headers(kwargs.get("headers"))

        url = normalize_url(merge_params(url, kwargs.get("params")))
        url_str = str(url)
        for prefix in self._passthrough:
            if url_str.startswith(prefix):
                return await self.patcher.temp_original(orig_self, method, url_origin, *args, **kwargs)

        key = (method, url)
        self.requests.setdefault(key, [])
        request_call = self._build_request_call(method, *args, **kwargs)
        self.requests[key].append(request_call)

        response = await self.match(method, url, **kwargs)

        if response is None:
            if self.passthrough_unmatched:
                return await self.patcher.temp_original(orig_self, method, url_origin, *args, **kwargs)
            raise ClientConnectionError(f"Connection refused: {method} {url}")
        self._responses.append(response)

        # Automatically call response.raise_for_status() on a request if the
        # request was initialized with raise_for_status=True. Also call
        # response.raise_for_status() if the client session was initialized
        # with raise_for_status=True, unless the request was called with
        # raise_for_status=False.
        raise_for_status = kwargs.get("raise_for_status")
        if raise_for_status is None:
            raise_for_status = getattr(orig_self, "_raise_for_status", False)

        if callable(raise_for_status):
            await raise_for_status(response)
        elif raise_for_status:
            response.raise_for_status()

        return response

    def _build_request_call(self, method: str = hdrs.METH_GET, *args: Any, allow_redirects: bool = True, **kwargs: Any):
        """Return request call."""
        kwargs.setdefault("allow_redirects", allow_redirects)
        if method == "POST":
            kwargs.setdefault("data", None)

        try:
            kwargs_copy = copy.deepcopy(kwargs)
        except (TypeError, ValueError):
            # Handle the fact that some values cannot be deep copied
            kwargs_copy = kwargs
        return RequestCall(args, kwargs_copy)
