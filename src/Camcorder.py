import shutil, datetime
from Exceptions import *
from HttpServer import *
from VideoRecorder import *
from FrameRecorder import *
from FrameStorage import *
from Syslog import *
from Timelapse import *



class Camcorder():
    def __init__(s, dvr, conf, dvrConf):
        s.dvr = dvr
        s.db = dvr.db
        s.sp = dvr.sp
        s.varStorage = dvr.varStorage
        s._name = conf['name']
        s.conf = conf
        s.dvrConf = dvrConf
        s.cron = dvr.cron
        s.log = Syslog('Camcorder_%s' % s.name())

        s.audioCodec = conf['audio']['codec'] if 'audio' in conf else None
        s.audioSampleRate = conf['audio']['sampleRate'] if 'audio' in conf else None

        s.vr = VideoRecorder(s)
        s.fr = FrameRecorder(s)

        s.fsDay = FrameStorage(s, 'day', ('*/15 * 0-7 * * *',
                                          '*/5 * 8-21 * * *',
                                          '*/10 * 22-23 * * *'))
        s.fsWeek = FrameStorage(s, 'week', ('*/30 * 7-21 * * *',))
        s.fsMonth = FrameStorage(s, 'month', ('0 */2 7-21 * * *',))
        s.fsYear = FrameStorage(s, 'year', ('0 */15 9-15 * * *',))

        s.fsDay.mkTimelapseByCron(s.cron.worker('Timelapse_day'))
        s.fsWeek.mkTimelapseByCron(s.cron.worker('Timelapse_week'))
        s.fsMonth.mkTimelapseByCron(s.cron.worker('Timelapse_month'))
        s.fsYear.mkTimelapseByCron(s.cron.worker('Timelapse_year'))

        s.jpegDir = '%s/%s' % (s.dvrConf['frameRecorder']['jpegDir'], s.name())


    def options(s):
        return s.conf['options']


    def name(s):
        return s._name


    def description(s):
        return s.conf['desc']


    def toAdmin(s, msg):
        s.dvr.toAdmin("Camcorder %s: %s" % (s.name(), msg))


    def rtsp(s):
        return s.conf['rtsp']


    def start(s):
        s.vr.start()
        s.fr.start()


    def stop(s):
        s.vr.stop()
        s.fr.stop()


    def stat(s):
        return {'name': s.name(),
                'desc': s.description(),
                'isRecordStarted': s.isStarted(),
                'isRecording': s.isRecording(),
                'dataSize': s.size(),
                'duration': s.duration()}


    def resetStat(s):
        s.vr.resetStat()


    def captureJpegFrame(s):
        def do(fName, created):
            fdate = datetime.datetime.fromtimestamp(created)
            newFName = "%s/%s" % (s.jpegDir, fdate.strftime("%Y_%d_%m_%H_%M_%S.jpg"))
            try:
                shutil.copyfile(fName, newFName)
                return newFName
            except OSError as e:
                raise CamFramerNoDataErr(s.log, 'can`t copy %s to %s: %s' % (
                                         fName, newFName, e)) from e
        return s.fr.processFile(do)


    def __repr__(s):
        return "Dvr.Camcorder:%s" % s.name()






