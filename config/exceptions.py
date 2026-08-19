from rest_framework import status
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response

    codes = exc.get_codes() if hasattr(exc, "get_codes") else None
    if isinstance(codes, str):
        error_code = codes
    else:
        default_code = getattr(exc, "default_code", "api_error")
        error_code = (
            default_code
            if isinstance(default_code, str)
            else "validation_error"
            if response.status_code == 400
            else "api_error"
        )

    if isinstance(response.data, dict) and "detail" in response.data:
        message = str(response.data["detail"])
        details = {}
    else:
        message = "The request could not be completed."
        details = response.data
        if response.status_code == status.HTTP_400_BAD_REQUEST:
            error_code = "validation_error"

    response.data = {
        "error": {"code": error_code, "message": message, "details": details}
    }
    return response
