from Storage import *


class VarStorage(Storage):
    def __init__(s, dvr, fileName):
        s.dvr = dvr
        storageDir = dvr.conf.dvr['varStorageDir']
        super().__init__(fileName, storageDir)
