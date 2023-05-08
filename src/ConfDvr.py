from ConfParser import *


class ConfDvr(ConfParser):
    def __init__(s):
        super().__init__()
        s.addConfig('dvr', 'dvr.conf')
        s.addConfig('telegram', 'telegram.conf')
        s.addConfig('db', 'database.conf')
        s.addConfig('cameras', 'cameras.conf')


