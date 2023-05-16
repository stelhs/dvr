from sr90Exceptions import *

# Database errors:

class DatabaseConnectorError(AppError):
    pass

class DatabaseConnectorQueryError(DatabaseConnectorError):
    pass

class DatabaseConnectorConnectError(DatabaseConnectorError):
    pass


# Camera errors

class CameraNotRegistredError(AppError):
    pass

class CameraRecDurationError(AppError):
    pass

class OpenRtspError(AppError):
    pass

class OpenRtspAlreadyStarted(OpenRtspError):
    pass

class OpenRtspAlreadyStopped(OpenRtspError):
    pass

class OpenRtspCanNotStopError(OpenRtspError):
    pass

class ImageRecordingError(AppError):
    pass

class ImageRecordingAlreadyStartedError(ImageRecordingError):
    pass

class ImageRecordingAlreadyStoppedError(ImageRecordingError):
    pass

class ImageRecordingNoImageError(ImageRecordingError):
    pass
