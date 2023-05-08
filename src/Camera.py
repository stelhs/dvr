import subprocess, os
from Syslog import *
from Task import *



class Camera():
    def __init__(s, dvr, name, conf):
        s.dvr = dvr
        s.db = dvr.db
        s._name = name
        s.conf = conf
        s.log = Syslog("Camera_%s" % name)
        s.pidDir = s.dvr.conf.dvr['pidDir']
        s.audioCodec = conf['audio']['codec'] if 'audio' in conf else None
        s.audioSampleRate = conf['audio']['sampleRate'] if 'audio' in conf else None
        s.stopFlag = False
        s.hideErrors = True if 'HIDE_ERRORS' in conf['options'] else False


    def name(s):
        return s._name


    def description(s):
        return s.conf['desc']


    def pidFileName(s):
        return '%s/camera_%s_pid' % (s.pidDir, s.name())


    def pid(s):
        fname = s.pidFileName()
        if not os.path.exists(fname):
            return None

        try:
            pid = int(fileGetContent(fname))
        except FileError:
            return None
        return pid


    def rtsp(s):
        return s.conf['rtsp']


    def start(s):
        if s.isRecording():
            raise OpenRtspAlreadyStarted(s.log,
                    "Can't starting camera '%s' recording. " \
                    "Recording already was started" % s.name())

        s.stopFlag = False
        Task.asyncRunSingle('recording_%s' % s.name(), s.openRtspTask)


    def stop(s):
        if not s.isRecording():
            raise OpenRtspAlreadyStopped(s.log,
                    "Can't stopping camera '%s' recording. " \
                    "Recording already was stopped" % s.name())
        s.stopFlag = True
        cnt = 0
        while (s.isRecording()):
            if cnt > 5:
                raise OpenRtspCanNotStopError(s.log, "Can't stop camera '%s'" % s.name())
            pid = s.pid()
            if not pid:
                break

            os.system('kill %s' % s.pid())
            cnt += 1
            Task.sleep(1000)

        s.log.info("camera '%s' recording has stopped" % s.name())
        print("camera '%s' recording has stopped" % s.name())


    def restart(s):
        try:
            s.stop()
        except OpenRtspAlreadyStopped:
            pass
        s.start()


    def size(s):
        row = s.db.query("select sum(file_size) as size "\
                         "from videos where cam_name = '%s'" %
                         s.name())
        if 'size' not in row:
            return 0
        return int(row['size'])


    def duration(s):
        row = s.db.query("select sum(duration) as sum from videos "\
                         "where cam_name = '%s' and file_size is not NULL" %
                          s.name());
        if 'sum' not in row:
            return 0
        return int(row['sum'])


    def openRtspTask(s):
        openRtspCmd = "/usr/local/bin/openRTSP " \
              "-D 20 -K -b 1000000 -P %d -c -t -f %d " \
              "-F %s -N %s -j %s %s" % (
                   s.dvr.conf.dvr['videoFileDuration'],
                   s.conf['video']['frameRate'],
                   s.name(), '/root/dvr/src/open_rtsp_callback.sh',
                   s.pidFileName(), s.rtsp())

        while True:
            s.log.info("camera '%s' recording has started" % s.name())
            p = subprocess.run(openRtspCmd.split(' '), shell=False,
                               capture_output=True, text=True)
            if p.returncode:
                s.log.err("openRTSP %s fallout" % s.name())
                if s.name() == 'west_post':
                    print("%s: p.returncode = %d" % (s.name(), p.returncode))

            try:
                os.unlink(s.pidFileName())
            except FileNotFoundError:
                pass

            if s.stopFlag:
                return

            Task.sleep(1000)


    def isRecording(s):
        if not os.path.exists(s.pidFileName()):
            return False

        pid = s.pid()
        if not os.path.exists("/proc/%d" % pid):
            return False

        return True


    def __repr__(s):
        return "Dvr.Camera:%s" % s.name()




