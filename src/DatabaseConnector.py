import threading
from Exceptions import *
from Syslog import *
from Task import *
from MySQL import *


class DatabaseConnector():
    def __init__(s, skynet, conf):
        s.skynet = skynet
        s.conf = conf
        s.tc = skynet.tc
        s.log = Syslog('DatabaseConnector')
        s.mysql = MySQL(conf)
        s.attempts = 0
        s.task = Task('DatabaseConnector', s.reconnector)
        s.task.start()
        s._lock = threading.Lock()


    def toAdmin(s, msg):
        if not s.tc:
            s.tc = s.skynet
        if s.tc:
            s.tc.toAdmin("DatabaseConnector: %s" % msg)


    def reconnector(s):
        while 1:
            if s.attempts > 30:
                s.toAdmin('Can`t connect to MySQL server')
                s.attempts = 0

            if not s.mysql.isClosed():
                s.mysql.close()

            try:
                s.mysql.connect()
            except mysql.connector.errors.DatabaseError:
                s.attempts += 1
                Task.sleep(1000)
                continue

            s.attempts = 0
            s.task.dropMessages()
            s.task.waitMessage()


    def waitForReconnect(s):
        s.task.sendMessage('doConnect')
        while 1:
            Task.sleep(500)
            if not s.mysql.isClosed():
                break


    def query(s, query):
        if s.mysql.isClosed():
            s.waitForReconnect()

        while 1:
            try:
                with s._lock:
                    return s.mysql.query(query)
            except mysql.connector.errors.ProgrammingError as e:
                raise DatabaseConnectorError(s.log, "query() '%s' error: %s" % (query, e)) from e
            except mysql.connector.errors.Error as e:
                s.log.info('Cant request query(): SQL query: "%s". Error: %s' % (query, e))
                s.waitForReconnect()


    def queryList(s, query):
        if s.mysql.isClosed():
            s.waitForReconnect()

        while 1:
            try:
                with s._lock:
                    return s.mysql.queryList(query)
            except mysql.connector.errors.ProgrammingError as e:
                raise DatabaseConnectorError(s.log, "queryList() '%s' error: %s" % (query, e)) from e
            except mysql.connector.errors.Error as e:
                s.log.info('Cant request queryList(): SQL query: "%s". Error: %s' % (query, e))
                s.waitForReconnect()


    def insert(s, tableName, dataWithComma=[], dataWithOutComma=[]):
        if s.mysql.isClosed():
            s.waitForReconnect()

        while 1:
            try:
                with s._lock:
                    return s.mysql.insert(tableName, dataWithComma, dataWithOutComma)
            except mysql.connector.errors.ProgrammingError as e:
                raise DatabaseConnectorError(s.log,
                        "insert() in table %s error: %s. " \
                        "dataWithComma: %s, dataWithOutComma: %s" % (
                            tableName, e, dataWithComma, dataWithOutComma)) from e
            except mysql.connector.errors.Error as e:
                s.log.info('Cant insert to table "%s": Error: %s' % (tableName, e))
                s.waitForReconnect()


    def update(s, tableName, id, dataWithComma=[], dataWithOutComma=[]):
        if s.mysql.isClosed():
            s.waitForReconnect()

        while 1:
            try:
                with s._lock:
                    return s.mysql.update(tableName, id, dataWithComma, dataWithOutComma)
            except mysql.connector.errors.ProgrammingError as e:
                raise DatabaseConnectorError(s.log,
                        "update() table %s, id:%d error: %s" % (tableName, id, e)) from e
            except mysql.connector.errors.Error as e:
                s.log.info('Cant update table "%s": SQL query: "%s". Error: %s' % (tableName, query, e))
                s.waitForReconnect()


    def destroy(s):
        print("destroy DatabaseConnector")
        with s._lock:
            s.mysql.close()



