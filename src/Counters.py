

class Counters():
    def __init__(s, v):
        s.vars = v


    def reset(s):
        for key, _ in s.vars.items():
            s.vars[key] = 0


    def inc(s, key):
        s.vars[key] += 1


    def __repr__(s):
        return "\n".join(["%s: %s" % (k,v) for k,v in s.vars.items()])
