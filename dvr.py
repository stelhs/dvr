import sys
import atexit
sys.path.append('sr90lib/')
sys.path.append('src/')

from math import *
import rlcompleter, readline
readline.parse_and_bind('tab:complete')

import resource

soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (4096, hard))


from Dvr import *
dvr = Dvr()


def exitCb():
    print("call exitCb")
    dvr.destroy()

atexit.register(exitCb)


print("help:")
print("\tdvr.camcorder('south')")
print("\tdvr.start()")

dvr.start()
dvr.finishTimelapses()
