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

        s.fsAll = (s.fsDay, s.fsWeek, s.fsMonth, s.fsYear)

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
        s.fr.start()
        if 'RECORDING' in s.options():
            s.vr.start()

        if 'TIMELAPSE' in s.options():
            for fs in s.fsAll:
                fs.enable()


    def stop(s):
        if s.vr.isStarted():
            s.vr.stop()
        if s.fr.isStarted():
            s.fr.stop()

        for fs in s.fsAll:
            fs.disable()


    def finishTimelapsesSync(s):
        for fs in s.fsAll:
            try:
                if not fs.tlps.isIncomplete():
                    continue
                print('Found not completed timelapse. ' \
                      'Start creator %s' % fs.tlps.name())
                fs.tlps.createSync()
                print('Finished timelapse %s' % fs.tlps.name())
            except AppError as e:
                print('Can`t finished timelapse %s: %s' % (fs.tlps.name(), e))


    def stat(s):
        return {'name': s.name(),
                'desc': s.description(),
                'isRecordStarted': s.vr.isStarted(),
                'isRecording': s.vr.isRecording(),
                'vrDataSize': s.vr.size(),
                'vrDuration': s.vr.duration()}


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






