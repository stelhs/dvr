from sr90Exceptions import *

# Database errors:

class DatabaseConnectorError(AppError):
    pass

class DatabaseConnectorQueryError(DatabaseConnectorError):
    pass

class DatabaseConnectorConnectError(DatabaseConnectorError):
    pass


# Camcorder errors

class CamNotRegistredErr(AppError):
    pass

class CamVideoErr(AppError):
    pass

class CamFrameRecorderErr(AppError):
    pass

class CamFramerNoDataErr(CamFrameRecorderErr):
    pass


# FrameStorage errors

class FrameStorageErr(AppError):
    pass


# Timelapce errors


class TimelapseErr(AppError):
    pass

class TimelapseCreatorErr(TimelapseErr):
    pass
