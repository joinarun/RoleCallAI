"""Typed domain errors mapped to API status codes at the edge."""


class RoleCallError(Exception):
    code = "rolecall_error"
    status_code = 400


class NotFoundError(RoleCallError):
    code = "not_found"
    status_code = 404


class ConflictError(RoleCallError):
    code = "conflict"
    status_code = 409


class ForbiddenError(RoleCallError):
    code = "forbidden"
    status_code = 403


class UnauthorizedError(RoleCallError):
    code = "unauthorized"
    status_code = 401


class RateLimitError(RoleCallError):
    code = "rate_limited"
    status_code = 429


class InvalidTransitionError(ConflictError):
    code = "invalid_transition"
