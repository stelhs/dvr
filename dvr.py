import sys
import atexit
sys.path.append('sr90lib/')
sys.path.append('src/')

from math import *
import rlcompleter, readline
readline.parse_and_bind('tab:complete')


from Dvr import *

dvr = Dvr()


def exitCb():
    print("call exitCb")
    dvr.destroy()

atexit.register(exitCb)


print("help:")
print("\tdvr.camera('south')")
print("\tdvr.start()")

dvr.start()