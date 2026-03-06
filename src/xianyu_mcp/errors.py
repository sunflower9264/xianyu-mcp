"""Error definitions and exception handling."""

from enum import Enum
from typing import Optional


class ErrorCode(str, Enum):
    """Error codes for the MCP service."""

    # General errors
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"

    # Browser errors
    BROWSER_START_FAILED = "BROWSER_START_FAILED"
    BROWSER_CRASHED = "BROWSER_CRASHED"
    BROWSER_NOT_INITIALIZED = "BROWSER_NOT_INITIALIZED"
    PAGE_TIMEOUT = "PAGE_TIMEOUT"
    PAGE_LOAD_FAILED = "PAGE_LOAD_FAILED"
    NAVIGATION_FAILED = "NAVIGATION_FAILED"

    # Login errors
    NOT_LOGGED_IN = "NOT_LOGGED_IN"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGIN_TIMEOUT = "LOGIN_TIMEOUT"
    QRCODE_NOT_FOUND = "QRCODE_NOT_FOUND"
    LOGOUT_FAILED = "LOGOUT_FAILED"

    # Operation errors
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
    SCREENSHOT_FAILED = "SCREENSHOT_FAILED"
    INVALID_PARAMETER = "INVALID_PARAMETER"

    # Network errors
    NETWORK_ERROR = "NETWORK_ERROR"
    REQUEST_FAILED = "REQUEST_FAILED"


class XianyuMCPError(Exception):
    """Base exception for Xianyu MCP service."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        details: Optional[dict] = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class BrowserError(XianyuMCPError):
    """Browser-related errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.BROWSER_START_FAILED,
        details: Optional[dict] = None
    ):
        super().__init__(message, code, details)


class LoginError(XianyuMCPError):
    """Login-related errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.LOGIN_FAILED,
        details: Optional[dict] = None
    ):
        super().__init__(message, code, details)


class OperationError(XianyuMCPError):
    """Operation-related errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.ELEMENT_NOT_FOUND,
        details: Optional[dict] = None
    ):
        super().__init__(message, code, details)

