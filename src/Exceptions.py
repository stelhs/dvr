from sr90Exceptions import *

# Database errors:

class DatabaseConnectorError(AppError):
    pass

class DatabaseConnectorQueryError(DatabaseConnectorError):
    pass

class DatabaseConnectorConnectError(DatabaseConnectorError):
    pass


# openRTSP errors

class OpenRtspError(AppError):
    pass

class CameraNotRegistredError(AppError):
    pass

class CameraRecDurationError(AppError):
    pass

class OpenRtspAlreadyStarted(OpenRtspError):
    pass

class OpenRtspAlreadyStopped(OpenRtspError):
    pass

class OpenRtspCanNotStopError(OpenRtspError):
    pass

